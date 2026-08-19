"""Image optimization: JPEG XL conversion, lossless in-place, and reverse."""
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from .containers import (
    _read_jxl_tags, _write_jxl_tags, _read_jpeg_xmp_tags, _insert_jpeg_xmp,
    _read_png_text, _strip_png_metadata, _inject_png_text, _encoder_dict,
    _identity_missing,
)
from .deps import HAS_PIL, Image
from .subproc import run_tool
from .paths import (
    VALID_EXTENSIONS, JPEG_QUALITY_MARKER, PNG_OPTIMIZATION_LEVEL, DEPS_DIR,
)
from .stats import (
    new_stats, _make_pbar, _pbar_skip, _pbar_update, _diff_bytes,
    _existing_size, _safe_remove, _walk_files, _collect_targets,
)
from .tools import detect_all_tools, _version_is_older
from .ui import log, fmt_size, print_header, c, Color, log_file_result

def _strip_jpeg_metadata(input_path, output_path):
    try:
        with open(input_path, "rb") as f:
            data = f.read()

        if not data.startswith(b"\xff\xd8"):
            return False

        out = bytearray(b"\xff\xd8")
        i = 2
        n = len(data)

        while i < n:
            while i < n and data[i] == 0xFF:
                i += 1
            if i >= n:
                break

            marker = data[i]
            i += 1

            if marker == 0xD8:
                continue

            if marker == 0xD9:
                out.extend(b"\xff\xd9")
                break

            if 0xD0 <= marker <= 0xD7:
                out.extend(b"\xff")
                out.extend(bytes([marker]))
                continue

            if marker == 0xDA:
                out.extend(b"\xff\xda")
                if i + 1 >= n:
                    return False
                length = (data[i] << 8) | data[i + 1]
                out.extend(data[i:i + length])
                i += length
                out.extend(data[i:])
                break

            if i + 1 >= n:
                return False

            length = (data[i] << 8) | data[i + 1]

            if 0xE0 <= marker <= 0xEF or marker == 0xFE:
                i += length
                continue

            out.extend(b"\xff")
            out.extend(bytes([marker]))
            out.extend(data[i:i + length])
            i += length

        with open(output_path, "wb") as f:
            f.write(out)

        return True
    except Exception:
        return False


def _png_has_alpha(filepath):
    if not HAS_PIL:
        return False, None
    img = None
    try:
        img = Image.open(filepath)
        has_alpha = (
            img.mode in ("RGBA", "LA")
            or (img.mode == "P" and "transparency" in img.info)
        )
        # Force a full read so PIL closes the underlying file handle;
        # otherwise later os.remove/os.replace of the same file fails on
        # Windows with WinError 32 while the caller still holds the image.
        try:
            img.load()
        except Exception:
            pass
        return has_alpha, img
    except Exception:
        if img is not None:
            try:
                img.close()
            except Exception:
                pass
        return False, None


def _flatten_png_alpha(src_path, dst_path):
    if not HAS_PIL:
        return False
    try:
        with Image.open(src_path) as img:
            img.convert("RGB").save(dst_path, format="PNG")
        return True
    except Exception:
        return False


def _rename_to_cover(filepath, new_ext=None):
    out_dir = os.path.dirname(filepath)
    ext = new_ext if new_ext else os.path.splitext(filepath)[1]
    cover_path = os.path.join(out_dir, "cover" + ext)

    if os.path.normpath(filepath) == os.path.normpath(cover_path):
        return filepath

    if os.path.exists(cover_path):
        try:
            os.remove(cover_path)
        except OSError:
            pass

    os.rename(filepath, cover_path)
    return cover_path


def _process_image_to_jxl(args):
    (
        cjxl_path,
        djxl_path,
        jxl_version,
        src_path,
        threads_to_use,
        effort,
        force,
        rename_to_cover,
        remove_alpha,
        enc,
    ) = args
    enabled = enc.get("jxl") or {}

    src_path = os.path.normpath(src_path)
    ext = os.path.splitext(src_path)[1].lower()
    out_dir = os.path.dirname(src_path)

    final_out_path = (
        os.path.join(out_dir, "cover.jxl")
        if rename_to_cover
        else os.path.splitext(src_path)[0] + ".jxl"
    )

    if os.path.normpath(src_path) == os.path.normpath(final_out_path):
        temp_out_path = os.path.join(out_dir, "cover.jxl.reencode.tmp")
    else:
        temp_out_path = final_out_path + ".tmp"

    temp_files = []

    try:
        try:
            original_size = os.path.getsize(src_path)
        except OSError as e:
            return (src_path, "failed", 0, 0, f"Cannot stat source: {e}")

        existing_dest_size = _existing_size(final_out_path, src_path)

        if ext == ".jxl" and not force:
            q, v = _read_jxl_tags(src_path)
            if not _identity_missing(enabled, q, v):
                try:
                    if int(q) >= int(effort) and not _version_is_older(v, jxl_version):
                        return (
                            src_path,
                            "unchanged",
                            0,
                            0,
                            f"skipped (q={q}, v={v})",
                        )
                except (ValueError, TypeError):
                    pass

        _safe_remove(temp_out_path)

        input_for_cjxl = src_path
        use_strip_all = True
        force_no_reconstruction = False

        if ext in (".jpg", ".jpeg"):
            stripped_jpeg = src_path + ".no_meta.jpg"
            temp_files.append(stripped_jpeg)

            if _strip_jpeg_metadata(src_path, stripped_jpeg):
                input_for_cjxl = stripped_jpeg
                use_strip_all = False
            else:
                _safe_remove(stripped_jpeg)
                temp_files.remove(stripped_jpeg)
                force_no_reconstruction = True

        elif ext == ".png":
            if remove_alpha and HAS_PIL:
                has_alpha, _ = _png_has_alpha(src_path)
                if has_alpha:
                    stripped_png = src_path + ".no_alpha.png"
                    temp_files.append(stripped_png)

                    if _flatten_png_alpha(src_path, stripped_png):
                        input_for_cjxl = stripped_png
                    else:
                        _safe_remove(stripped_png)
                        temp_files.remove(stripped_png)

        elif ext == ".jxl":
            decoded_jpeg = src_path + ".decoded.jpg"
            temp_files.append(decoded_jpeg)

            try:
                djxl_result = run_tool(
                    [djxl_path, src_path, decoded_jpeg],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except Exception as e:
                return (src_path, "failed", 0, 0, f"djxl (JPEG) error: {e}")

            if (
                djxl_result.returncode == 0
                and os.path.exists(decoded_jpeg)
                and os.path.getsize(decoded_jpeg) > 0
            ):
                stripped_jpeg = src_path + ".no_meta.jpg"
                temp_files.append(stripped_jpeg)

                if _strip_jpeg_metadata(decoded_jpeg, stripped_jpeg):
                    input_for_cjxl = stripped_jpeg
                    use_strip_all = False
                else:
                    input_for_cjxl = decoded_jpeg
                    force_no_reconstruction = True
            else:
                _safe_remove(decoded_jpeg)
                temp_files.remove(decoded_jpeg)

                decoded_png = src_path + ".decoded.png"
                temp_files.append(decoded_png)

                try:
                    djxl_result = run_tool(
                        [djxl_path, src_path, decoded_png],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                except Exception as e:
                    return (src_path, "failed", 0, 0, f"djxl (PNG) error: {e}")

                if (
                    djxl_result.returncode != 0
                    or not os.path.exists(decoded_png)
                    or os.path.getsize(decoded_png) == 0
                ):
                    err = djxl_result.stderr.decode("utf-8", errors="replace").strip()
                    return (src_path, "failed", 0, 0, f"djxl decode failed: {err}")

                input_for_cjxl = decoded_png

                if remove_alpha and HAS_PIL:
                    has_alpha, _ = _png_has_alpha(decoded_png)
                    if has_alpha:
                        flat_png = decoded_png + ".no_alpha.png"
                        temp_files.append(flat_png)

                        if _flatten_png_alpha(decoded_png, flat_png):
                            input_for_cjxl = flat_png

        cmd = [
            cjxl_path,
            input_for_cjxl,
            temp_out_path,
            "-d", "0",
            "-e", str(effort),
            "-j", str(threads_to_use),
        ]

        if use_strip_all:
            cmd.extend(["-x", "strip=all"])

        if force_no_reconstruction:
            cmd.append("--allow_jpeg_reconstruction=0")

        try:
            result = run_tool(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            return (src_path, "failed", 0, 0, f"cjxl error: {e}")

        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace").strip()
            return (src_path, "failed", 0, 0, f"cjxl rc={result.returncode}: {err}")

        if not os.path.exists(temp_out_path):
            return (src_path, "failed", 0, 0, "Output not created")

        try:
            _write_jxl_tags(temp_out_path, effort, jxl_version, enabled)
        except Exception as e:
            log(f"[jxl tag warn] {src_path}: {e}")

        final_size = os.path.getsize(temp_out_path)

        try:
            os.remove(src_path)
        except OSError as e:
            return (src_path, "failed", 0, 0, f"Couldn't delete original: {e}")

        if (
            os.path.exists(final_out_path)
            and os.path.normpath(final_out_path) != os.path.normpath(temp_out_path)
        ):
            try:
                os.remove(final_out_path)
            except OSError as e:
                return (src_path, "failed", 0, 0, f"Couldn't overwrite: {e}")

        try:
            os.rename(temp_out_path, final_out_path)
        except OSError as e:
            return (src_path, "failed", 0, 0, f"Couldn't rename: {e}")

        b_rem, b_add = _diff_bytes(original_size, final_size, existing_dest_size)

        return (
            final_out_path,
            "modified",
            b_rem,
            b_add,
            f"{fmt_size(original_size)} -> {fmt_size(final_size)}",
        )

    finally:
        for f in temp_files:
            _safe_remove(f)
        _safe_remove(temp_out_path)


def _process_jpeg_in_place(args):
    jpegtran_exe, ljt_version, filepath, force, rename_to_cover, enc = args
    enabled = enc.get("jpeg") or {}

    filename = os.path.basename(filepath)
    temp_path = filepath + ".opttmp.jpg"

    try:
        original_size = os.path.getsize(filepath)
    except OSError as e:
        return (filename, "failed", 0, 0, f"cannot stat: {e}")

    existing_dest_size = 0
    if rename_to_cover:
        cover_path = os.path.join(os.path.dirname(filepath), "cover.jpg")
        existing_dest_size = _existing_size(cover_path, filepath)

    if not force:
        q, v = _read_jpeg_xmp_tags(filepath)
        if not _identity_missing(enabled, q, v):
            try:
                if int(q) >= JPEG_QUALITY_MARKER and not _version_is_older(v, ljt_version):
                    return (
                        filename,
                        "unchanged",
                        0,
                        0,
                        f"skipped (q={q}, v={v})",
                    )
            except (ValueError, TypeError):
                pass

    _safe_remove(temp_path)

    cmd = [
        jpegtran_exe,
        "-copy", "none",
        "-optimize",
        "-progressive",
        "-outfile", temp_path,
        filepath,
    ]

    try:
        result = run_tool(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        if result.returncode != 0:
            err = (result.stderr or "").strip()
            return (filename, "failed", 0, 0, f"jpegtran failed: {err}")

        if not os.path.exists(temp_path):
            return (filename, "failed", 0, 0, "jpegtran produced no output")

        os.replace(temp_path, filepath)
        temp_path = None

        try:
            _insert_jpeg_xmp(
                filepath,
                JPEG_QUALITY_MARKER,
                ljt_version,
                "libjpeg-turbo/jpegtran",
                enabled,
            )
        except Exception as e:
            log(f"[jpeg tag warn] {filepath}: {e}")

        if rename_to_cover:
            filepath = _rename_to_cover(filepath, ".jpg")

        final_size = os.path.getsize(filepath)
        b_rem, b_add = _diff_bytes(original_size, final_size, existing_dest_size)

        info = f"{original_size // 1024} KB -> {final_size // 1024} KB"

        if rename_to_cover and os.path.basename(filepath) == "cover.jpg":
            info += " (cover.jpg)"

        return (filepath, "modified", b_rem, b_add, info)

    except Exception as e:
        return (filename, "failed", 0, 0, f"exception: {e}")

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _process_png_in_place(args):
    (
        oxipng_exe,
        oxipng_version,
        filepath,
        force,
        rename_to_cover,
        remove_alpha,
        enc,
    ) = args
    enabled = enc.get("png") or {}

    filename = os.path.basename(filepath)
    temp_path = filepath + ".opttmp.png"

    try:
        original_size = os.path.getsize(filepath)
    except OSError as e:
        return (filename, "failed", 0, 0, f"cannot stat: {e}")

    existing_dest_size = 0
    if rename_to_cover:
        cover_path = os.path.join(os.path.dirname(filepath), "cover.png")
        existing_dest_size = _existing_size(cover_path, filepath)

    if not force:
        tags = _read_png_text(filepath)
        q = tags.get("ENCODER_QUALITY")
        v = tags.get("ENCODER_VERSION")

        if not _identity_missing(enabled, q, v):
            try:
                if int(q) >= PNG_OPTIMIZATION_LEVEL and not _version_is_older(v, oxipng_version):
                    return (
                        filename,
                        "unchanged",
                        0,
                        0,
                        f"skipped (q={q}, v={v})",
                    )
            except (ValueError, TypeError):
                pass

    _safe_remove(temp_path)

    if remove_alpha and HAS_PIL:
        has_alpha, _ = _png_has_alpha(filepath)
        if has_alpha:
            flat_path = filepath + ".no_alpha.png"

            try:
                if _flatten_png_alpha(filepath, flat_path):
                    os.replace(flat_path, filepath)
                else:
                    _safe_remove(flat_path)
            except Exception:
                _safe_remove(flat_path)

    cmd = [
        oxipng_exe,
        "-o", str(PNG_OPTIMIZATION_LEVEL),
        "--strip", "safe",
        "--force",
        "--output", temp_path,
        filepath,
    ]

    try:
        result = run_tool(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        if result.returncode != 0:
            err = (result.stderr or "").strip()
            return (filename, "failed", 0, 0, f"oxipng failed: {err}")

        if not os.path.exists(temp_path):
            shutil.copy2(filepath, temp_path)

        os.replace(temp_path, filepath)
        temp_path = None

        try:
            _strip_png_metadata(filepath)
        except Exception as e:
            log(f"[png strip warn] {filepath}: {e}")

        try:
            _inject_png_text(
                filepath,
                _encoder_dict("oxipng", PNG_OPTIMIZATION_LEVEL,
                              oxipng_version, enabled),
            )
        except Exception as e:
            log(f"[png tag warn] {filepath}: {e}")

        if rename_to_cover:
            filepath = _rename_to_cover(filepath, ".png")

        final_size = os.path.getsize(filepath)
        b_rem, b_add = _diff_bytes(original_size, final_size, existing_dest_size)

        info = f"{original_size // 1024} KB -> {final_size // 1024} KB"

        if rename_to_cover and os.path.basename(filepath) == "cover.png":
            info += " (cover.png)"

        return (filepath, "modified", b_rem, b_add, info)

    except Exception as e:
        return (filename, "failed", 0, 0, f"exception: {e}")

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _process_jxl_in_place(args):
    (
        cjxl_path,
        djxl_path,
        jxl_version,
        src_path,
        threads_to_use,
        effort,
        force,
        rename_to_cover,
        enc,
    ) = args
    enabled = enc.get("jxl") or {}

    filename = os.path.basename(src_path)
    temp_out_path = src_path + ".opttmp.jxl"
    temp_files = []

    try:
        try:
            original_size = os.path.getsize(src_path)
        except OSError as e:
            return (filename, "failed", 0, 0, f"cannot stat: {e}")

        existing_dest_size = 0
        if rename_to_cover:
            cover_path = os.path.join(os.path.dirname(src_path), "cover.jxl")
            existing_dest_size = _existing_size(cover_path, src_path)

        if not force:
            q, v = _read_jxl_tags(src_path)
            if not _identity_missing(enabled, q, v):
                try:
                    if int(q) >= int(effort) and not _version_is_older(v, jxl_version):
                        return (
                            filename,
                            "unchanged",
                            0,
                            0,
                            f"skipped (q={q}, v={v})",
                        )
                except (ValueError, TypeError):
                    pass

        decoded_jpeg = src_path + ".decoded.jpg"
        temp_files.append(decoded_jpeg)

        input_for_cjxl = None
        use_strip_all = True
        force_no_reconstruction = False

        try:
            djxl_result = run_tool(
                [djxl_path, src_path, decoded_jpeg],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            return (filename, "failed", 0, 0, f"djxl (JPEG) error: {e}")

        if (
            djxl_result.returncode == 0
            and os.path.exists(decoded_jpeg)
            and os.path.getsize(decoded_jpeg) > 0
        ):
            stripped_jpeg = src_path + ".no_meta.jpg"
            temp_files.append(stripped_jpeg)

            if _strip_jpeg_metadata(decoded_jpeg, stripped_jpeg):
                input_for_cjxl = stripped_jpeg
                use_strip_all = False
            else:
                input_for_cjxl = decoded_jpeg
                force_no_reconstruction = True
        else:
            _safe_remove(decoded_jpeg)
            temp_files.remove(decoded_jpeg)

            decoded_png = src_path + ".decoded.png"
            temp_files.append(decoded_png)

            try:
                djxl_result = run_tool(
                    [djxl_path, src_path, decoded_png],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except Exception as e:
                return (filename, "failed", 0, 0, f"djxl (PNG) error: {e}")

            if (
                djxl_result.returncode != 0
                or not os.path.exists(decoded_png)
                or os.path.getsize(decoded_png) == 0
            ):
                err = djxl_result.stderr.decode("utf-8", errors="replace").strip()
                return (filename, "failed", 0, 0, f"djxl decode failed: {err}")

            input_for_cjxl = decoded_png

        cmd = [
            cjxl_path,
            input_for_cjxl,
            temp_out_path,
            "-d", "0",
            "-e", str(effort),
            "-j", str(threads_to_use),
        ]

        if use_strip_all:
            cmd.extend(["-x", "strip=all"])

        if force_no_reconstruction:
            cmd.append("--allow_jpeg_reconstruction=0")

        try:
            result = run_tool(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            return (filename, "failed", 0, 0, f"cjxl error: {e}")

        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace").strip()
            return (filename, "failed", 0, 0, f"cjxl rc={result.returncode}: {err}")

        if not os.path.exists(temp_out_path):
            return (filename, "failed", 0, 0, "Output not created")

        try:
            _write_jxl_tags(temp_out_path, effort, jxl_version, enabled)
        except Exception as e:
            log(f"[jxl tag warn] {src_path}: {e}")

        final_size = os.path.getsize(temp_out_path)
        os.replace(temp_out_path, src_path)
        temp_out_path = None

        if rename_to_cover:
            src_path = _rename_to_cover(src_path, ".jxl")

        final_size = os.path.getsize(src_path)
        b_rem, b_add = _diff_bytes(original_size, final_size, existing_dest_size)

        info = f"{original_size // 1024} KB -> {final_size // 1024} KB"

        if rename_to_cover and os.path.basename(src_path) == "cover.jxl":
            info += " (cover.jxl)"

        return (src_path, "modified", b_rem, b_add, info)

    finally:
        for f in temp_files:
            _safe_remove(f)
        _safe_remove(temp_out_path)


def _process_jxl_back_to_original(args):
    (
        djxl_path,
        jpegtran_exe,
        ljt_version,
        oxipng_exe,
        oxipng_version,
        src_path,
        rename_to_cover,
        remove_alpha,
        remove_alpha_pil,
        force,
        enc,
    ) = args

    filename = os.path.basename(src_path)
    temp_files = []

    try:
        try:
            original_size = os.path.getsize(src_path)
        except OSError as e:
            return (src_path, "failed", 0, 0, f"cannot stat: {e}")

        decoded_jpeg = src_path + ".decoded.jpg"
        temp_files.append(decoded_jpeg)

        try:
            djxl_result = run_tool(
                [djxl_path, src_path, decoded_jpeg],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            return (src_path, "failed", 0, 0, f"djxl (JPEG) error: {e}")

        if (
            djxl_result.returncode == 0
            and os.path.exists(decoded_jpeg)
            and os.path.getsize(decoded_jpeg) > 0
        ):
            out_path = (
                os.path.join(os.path.dirname(src_path), "cover.jpg")
                if rename_to_cover
                else os.path.splitext(src_path)[0] + ".jpg"
            )

            existing_dest_size = _existing_size(out_path, src_path)

            stripped_jpeg = src_path + ".no_meta.jpg"
            temp_files.append(stripped_jpeg)

            if _strip_jpeg_metadata(decoded_jpeg, stripped_jpeg):
                input_file = stripped_jpeg
            else:
                input_file = decoded_jpeg

            if jpegtran_exe:
                optimized = src_path + ".optimized.jpg"
                temp_files.append(optimized)

                try:
                    result = run_tool(
                        [
                            jpegtran_exe,
                            "-copy", "none",
                            "-optimize",
                            "-progressive",
                            "-outfile", optimized,
                            input_file,
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                    )

                    final_input = (
                        optimized
                        if result.returncode == 0 and os.path.exists(optimized)
                        else input_file
                    )
                except Exception:
                    final_input = input_file
            else:
                final_input = input_file

            try:
                os.remove(src_path)
            except OSError as e:
                return (src_path, "failed", 0, 0, f"Couldn't delete JXL: {e}")

            if (
                os.path.exists(out_path)
                and os.path.normpath(final_input) != os.path.normpath(out_path)
            ):
                os.remove(out_path)

            os.replace(final_input, out_path)

            if jpegtran_exe:
                enc_ver = ljt_version
                program = "libjpeg-turbo/jpegtran"
                quality = JPEG_QUALITY_MARKER
            else:
                enc_ver = "decoded"
                program = "djxl/decoded"
                quality = 0

            try:
                _insert_jpeg_xmp(out_path, quality, enc_ver, program,
                                 enc.get("jpeg") or {})
            except Exception as e:
                log(f"[jpeg tag warn] {out_path}: {e}")

            final_size = os.path.getsize(out_path)
            b_rem, b_add = _diff_bytes(original_size, final_size, existing_dest_size)

            info = f"JXL -> JPEG: {original_size // 1024} KB -> {final_size // 1024} KB"

            if rename_to_cover:
                info += " (cover.jpg)"

            return (out_path, "modified", b_rem, b_add, info)

        _safe_remove(decoded_jpeg)
        temp_files.remove(decoded_jpeg)

        decoded_png = src_path + ".decoded.png"
        temp_files.append(decoded_png)

        try:
            djxl_result = run_tool(
                [djxl_path, src_path, decoded_png],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            return (src_path, "failed", 0, 0, f"djxl (PNG) error: {e}")

        if (
            djxl_result.returncode != 0
            or not os.path.exists(decoded_png)
            or os.path.getsize(decoded_png) == 0
        ):
            err = djxl_result.stderr.decode("utf-8", errors="replace").strip()
            return (src_path, "failed", 0, 0, f"djxl decode failed: {err}")

        out_path = (
            os.path.join(os.path.dirname(src_path), "cover.png")
            if rename_to_cover
            else os.path.splitext(src_path)[0] + ".png"
        )

        existing_dest_size = _existing_size(out_path, src_path)

        input_file = decoded_png

        if remove_alpha and remove_alpha_pil:
            has_alpha, _ = _png_has_alpha(decoded_png)
            if has_alpha:
                flat_png = decoded_png + ".no_alpha.png"
                temp_files.append(flat_png)

                if _flatten_png_alpha(decoded_png, flat_png):
                    input_file = flat_png

        if oxipng_exe:
            optimized = src_path + ".optimized.png"
            temp_files.append(optimized)

            try:
                result = run_tool(
                    [
                        oxipng_exe,
                        "-o", str(PNG_OPTIMIZATION_LEVEL),
                        "--strip", "safe",
                        "--force",
                        "--output", optimized,
                        input_file,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                final_input = (
                    optimized
                    if result.returncode == 0 and os.path.exists(optimized)
                    else input_file
                )
            except Exception:
                final_input = input_file
        else:
            final_input = input_file

        try:
            os.remove(src_path)
        except OSError as e:
            return (src_path, "failed", 0, 0, f"Couldn't delete JXL: {e}")

        if (
            os.path.exists(out_path)
            and os.path.normpath(final_input) != os.path.normpath(out_path)
        ):
            os.remove(out_path)

        os.replace(final_input, out_path)

        try:
            _strip_png_metadata(out_path)
        except Exception:
            pass

        if oxipng_exe:
            enc_ver = oxipng_version
            program = "oxipng"
            quality = PNG_OPTIMIZATION_LEVEL
        else:
            enc_ver = "decoded"
            program = "djxl/decoded"
            quality = 0

        try:
            _inject_png_text(
                out_path,
                _encoder_dict(program, quality, enc_ver,
                              enc.get("png") or {}),
            )
        except Exception as e:
            log(f"[png tag warn] {out_path}: {e}")

        final_size = os.path.getsize(out_path)
        b_rem, b_add = _diff_bytes(original_size, final_size, existing_dest_size)

        info = f"JXL -> PNG: {original_size // 1024} KB -> {final_size // 1024} KB"

        if rename_to_cover:
            info += " (cover.png)"

        return (out_path, "modified", b_rem, b_add, info)

    except Exception as e:
        return (src_path, "failed", 0, 0, f"exception: {e}")

    finally:
        for f in temp_files:
            _safe_remove(f)


def run_process_images(config):
    effort = config["jpegxl_effort"]
    target_dir = config["music_folder"]

    reencode_images = config.get("reencode_images", True)
    reencode_to_jxl = config.get("reencode_to_jxl", True)
    convert_jxl_back = config.get("convert_jxl_back", False)
    rename_to_cover = config.get("rename_to_cover", True)
    remove_alpha = config.get("remove_alpha", True)
    force = config.get("force_reencode_images", False)
    enc = config.get("encoder_tags") or {}

    stats = new_stats()

    if not reencode_images:
        print_header("Image Processing (skipped - reencode_images is False)")
        return stats

    tools = detect_all_tools()
    jxl_tool = tools.get("libjxl")

    if not jxl_tool:
        log(c("ERROR: Could not auto-detect libjxl in .dependencies folder.", Color.RED))
        log(f"Expected a folder like: {os.path.join(DEPS_DIR, 'libjxl v0.12.0')}")
        return stats

    cjxl_path = jxl_tool["cjxl_exe"]
    djxl_path = jxl_tool["djxl_exe"]
    jxl_version = jxl_tool["version"]

    if not djxl_path:
        log(c("ERROR: djxl.exe not found in libjxl folder (required).", Color.RED))
        return stats

    ljt = tools.get("libjpeg_turbo")
    ox = tools.get("oxipng")

    if not HAS_PIL and remove_alpha:
        log(c("WARNING: Pillow not found. Alpha removal will be skipped.", Color.YELLOW))
        log("Install it with: pip install Pillow")

    print_header("Image Processing")

    if convert_jxl_back and reencode_to_jxl:
        mode = "JXL->original for .jxl, JPEG/PNG->JXL for others"
    elif convert_jxl_back:
        mode = "JXL->original, in-place JPEG/PNG"
    elif reencode_to_jxl:
        mode = f"JPEG XL conversion (effort {effort})"
    else:
        mode = "Lossless in-place JPEG/PNG/JXL"

    log(f"mode: {mode}")
    log(f"target: {target_dir}")

    files = _collect_targets(config.get("targets"), VALID_EXTENSIONS)
    if not files:
        files = sorted(_walk_files(target_dir, VALID_EXTENSIONS))

    if not files:
        log("No image files found.")
        return stats

    cpu_count = os.cpu_count() or 1
    est_workers = min(len(files), cpu_count)
    threads_per_file = max(1, cpu_count // max(1, est_workers))

    tasks = []

    for f in files:
        ext = os.path.splitext(f)[1].lower()

        if ext == ".jxl" and convert_jxl_back:
            tasks.append((
                _process_jxl_back_to_original,
                (
                    djxl_path,
                    ljt["jpegtran_exe"] if ljt else None,
                    ljt["version"] if ljt else None,
                    ox["oxipng_exe"] if ox else None,
                    ox["version"] if ox else None,
                    f,
                    rename_to_cover,
                    remove_alpha,
                    HAS_PIL,
                    force,
                    enc,
                ),
                f,
            ))

        elif reencode_to_jxl:
            tasks.append((
                _process_image_to_jxl,
                (
                    cjxl_path,
                    djxl_path,
                    jxl_version,
                    f,
                    threads_per_file,
                    effort,
                    force,
                    rename_to_cover,
                    remove_alpha,
                    enc,
                ),
                f,
            ))

        else:
            if ext in (".jpg", ".jpeg"):
                if ljt:
                    tasks.append((
                        _process_jpeg_in_place,
                        (
                            ljt["jpegtran_exe"],
                            ljt["version"],
                            f,
                            force,
                            rename_to_cover,
                            enc,
                        ),
                        f,
                    ))
                else:
                    stats["skipped_count"] += 1

            elif ext == ".png":
                if ox:
                    tasks.append((
                        _process_png_in_place,
                        (
                            ox["oxipng_exe"],
                            ox["version"],
                            f,
                            force,
                            rename_to_cover,
                            remove_alpha,
                            enc,
                        ),
                        f,
                    ))
                else:
                    stats["skipped_count"] += 1

            elif ext == ".jxl":
                tasks.append((
                    _process_jxl_in_place,
                    (
                        cjxl_path,
                        djxl_path,
                        jxl_version,
                        f,
                        threads_per_file,
                        effort,
                        force,
                        rename_to_cover,
                        enc,
                    ),
                    f,
                ))

    if not tasks:
        log(f"No active image tasks after skips ({stats['skipped_count']} skipped).")
        return stats

    workers = min(len(tasks), cpu_count)
    counts = {"ok": 0, "skip": 0, "fail": 0}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(fn, args): src
            for (fn, args, src) in tasks
        }

        pbar = _make_pbar(len(future_map), "Images")

        for future in as_completed(future_map):
            src = future_map[future]

            try:
                src_path, status, b_rem, b_add, info = future.result()
            except Exception as e:
                stats["total_scanned"] += 1
                stats["error_count"] += 1
                stats["errors"].append((src, str(e)))
                _pbar_update(pbar, counts, kind="fail")
                continue

            if status in ("unchanged", "skipped"):
                stats["skipped_count"] += 1
                log_file_result(src, "skip", info=info or "unchanged")
                _pbar_skip(pbar, counts)
                continue

            stats["total_scanned"] += 1

            if status == "modified":
                stats["modified_count"] += 1
                stats["total_bytes_removed"] += b_rem
                stats["total_bytes_added"] += b_add
                log_file_result(src_path, "ok", b_rem, b_add)
                _pbar_update(pbar, counts, kind="ok")
            else:
                stats["error_count"] += 1
                stats["errors"].append((src_path, info))
                log_file_result(src_path, "fail", info=info)
                _pbar_update(pbar, counts, kind="fail")

        if pbar:
            pbar.close()

    return stats

