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
    _existing_size, _safe_remove, _walk_files, _collect_targets, worker_count,
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
        return False
    try:
        with Image.open(filepath) as img:
            # Force a full read so PIL releases the underlying file handle;
            # otherwise later os.remove/os.replace of the same file fails on
            # Windows with WinError 32 while the caller still holds it.
            try:
                img.load()
            except Exception:
                pass
            return (
                img.mode in ("RGBA", "LA")
                or (img.mode == "P" and "transparency" in img.info)
            )
    except Exception:
        return False


def _flatten_png_alpha(src_path, dst_path):
    if not HAS_PIL:
        return False
    try:
        with Image.open(src_path) as img:
            img.convert("RGB").save(dst_path, format="PNG")
        return True
    except Exception:
        return False


def _prepare_image_streamlined(src_path, dst_path, config, remove_alpha=False):
    """Streamlined Pillow pre-processing: alpha removal + cover crop/resize in one open.

    Combines the previously separate _flatten_png_alpha and _resize_and_crop_image
    passes into a single Image.open → convert → crop → resize → save, so a
    PNG→JXL with crop+alpha or a JPEG→JXL with crop does not pay two Pillow
    decode/encode cycles. Returns True when a new file was written to dst_path.
    """
    if not HAS_PIL or not src_path or not dst_path:
        return False
    try:
        with Image.open(src_path) as img:
            try:
                img.load()
            except Exception:
                pass
            # 1) Alpha handling (PNG only)
            if remove_alpha and img.mode in ("RGBA", "LA", "P"):
                if img.mode == "P" and "transparency" not in img.info and img.mode not in ("RGBA", "LA"):
                    pass
                else:
                    try:
                        # Flatten to RGB with white background for RGBA/LA, or convert P
                        if img.mode == "P":
                            img = img.convert("RGBA")
                        if img.mode in ("RGBA", "LA"):
                            bg = Image.new("RGB", img.size, (255, 255, 255))
                            if img.mode == "LA":
                                img = img.convert("RGBA")
                            bg.paste(img, mask=img.split()[-1])
                            img = bg
                        else:
                            img = img.convert("RGB")
                    except Exception:
                        try:
                            img = img.convert("RGB")
                        except Exception:
                            return False
            elif img.mode not in ("RGB", "RGBA", "LA", "P"):
                # Ensure a saveable mode for other formats
                try:
                    img = img.convert("RGB")
                except Exception:
                    pass
            elif img.mode == "P":
                try:
                    img = img.convert("RGB")
                except Exception:
                    pass

            # 2) Cover crop/resize (if enabled)
            did_cover = False
            if config is not None:
                ext = os.path.splitext(src_path)[1].lower()
                per_enabled = True
                if ext in (".jpg", ".jpeg"):
                    per_enabled = bool(config.get("cover_jpeg_enabled", True))
                elif ext == ".png":
                    per_enabled = bool(config.get("cover_png_enabled", True))
                elif ext == ".jxl":
                    per_enabled = bool(config.get("cover_jxl_enabled", True))
                if per_enabled:
                    re_en = bool(config.get("cover_resize_enabled", False))
                    cr_en = bool(config.get("cover_crop_enabled", False))
                    thr = float(config.get("cover_crop_threshold", 0.05) or 0.05)
                    tgt = _get_cover_target_size(ext, config) if re_en else 0
                    if (re_en and tgt > 0) or cr_en:
                        # Use a temp in-memory crop/resize via _resize_and_crop_image logic
                        # but operate on the already-opened img to avoid re-opening
                        # Create a temp file for the helper to read from — instead, do it inline
                        w, h = img.size
                        need_crop = False
                        if cr_en and thr >= 0:
                            try:
                                ratio = w / h if h else 1.0
                                if abs(ratio - 1.0) > thr:
                                    need_crop = True
                            except Exception:
                                need_crop = False
                        force_exact = bool(config.get("cover_force_exact_size", False))
                        if force_exact and re_en and tgt > 0 and w != h:
                            try:
                                if abs(w / h - 1.0) > thr:
                                    need_crop = True
                            except Exception:
                                need_crop = True
                        need_resize = False
                        if re_en and tgt > 0:
                            if not need_crop:
                                if w > tgt or h > tgt:
                                    need_resize = True
                            else:
                                sq = min(w, h)
                                if sq > tgt:
                                    need_resize = True
                        if need_crop or need_resize:
                            # Perform crop to threshold (not square) inline
                            if need_crop:
                                if w > h:
                                    target_w = int(h * (1.0 + thr))
                                    target_w = max(h, min(target_w, w))
                                    left = (w - target_w) // 2
                                    img = img.crop((left, 0, left + target_w, h))
                                else:
                                    target_h = int(w * (1.0 + thr))
                                    target_h = max(w, min(target_h, h))
                                    top = (h - target_h) // 2
                                    img = img.crop((0, top, w, top + target_h))
                            if need_resize:
                                try:
                                    resample = Image.Resampling.LANCZOS
                                except AttributeError:
                                    resample = Image.LANCZOS
                                img = img.resize((tgt, tgt), resample)
                            did_cover = True

            # Save to dst_path with appropriate format (infer from dst ext, fallback to src)
            ext_dst = os.path.splitext(dst_path)[1].lower() or os.path.splitext(src_path)[1].lower()
            save_kwargs = {}
            if ext_dst in (".jpg", ".jpeg"):
                if img.mode in ("RGBA", "LA", "P"):
                    try:
                        bg = Image.new("RGB", img.size, (255, 255, 255))
                        if img.mode == "LA":
                            img = img.convert("RGBA")
                        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                        img = bg
                    except Exception:
                        img = img.convert("RGB")
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                save_kwargs["format"] = "JPEG"
                save_kwargs["quality"] = 95
                save_kwargs["optimize"] = True
            elif ext_dst == ".png":
                save_kwargs["format"] = "PNG"
                save_kwargs["optimize"] = True
            else:
                # For JXL temp or other, save as PNG to preserve lossless
                save_kwargs["format"] = "PNG"
                save_kwargs["optimize"] = True

            img.save(dst_path, **save_kwargs)
            return True
    except Exception:
        return False
    return False


def _get_cover_target_size(ext, config):
    """Return per-format cover target size (0 = use global).

    If the per-format override is >0 it wins, otherwise the global
    cover_target_size is used. Values are clamped to 0-4000.
    """
    if config is None:
        config = {}
    ext = (ext or "").lower()
    try:
        global_size = int(config.get("cover_target_size", 0) or 0)
    except (TypeError, ValueError):
        global_size = 0
    global_size = max(0, min(4000, global_size))
    per_size = 0
    try:
        if ext in (".jpg", ".jpeg"):
            per_size = int(config.get("cover_jpeg_target_size", 0) or 0)
        elif ext == ".png":
            per_size = int(config.get("cover_png_target_size", 0) or 0)
        elif ext == ".jxl":
            per_size = int(config.get("cover_jxl_target_size", 0) or 0)
    except (TypeError, ValueError):
        per_size = 0
    if per_size > 0:
        return max(0, min(4000, per_size))
    return global_size


def _should_resize_cover(src_path, config):
    """Whether cover resize should be attempted for *src_path*.

    Checks global cover_resize_enabled, per-format enabled and
    target_size >0. Requires Pillow.
    """
    if not config or not config.get("cover_resize_enabled"):
        return False
    if not HAS_PIL:
        return False
    ext = os.path.splitext(src_path)[1].lower() if src_path else ""
    if ext in (".jpg", ".jpeg"):
        if not config.get("cover_jpeg_enabled", True):
            return False
    elif ext == ".png":
        if not config.get("cover_png_enabled", True):
            return False
    elif ext == ".jxl":
        if not config.get("cover_jxl_enabled", True):
            return False
    target = _get_cover_target_size(ext, config)
    return target > 0


def _resize_and_crop_image(src_path, dst_path, target_size, crop_enabled, crop_threshold, config=None):
    """Resize and/or center-crop a cover image via Pillow.

    * If *crop_enabled* and aspect deviation > *crop_threshold*, center-crop
      the longer side to a square. When ``cover_force_exact_size`` is True
      and a resize target is set, the image is *always* center-cropped to a
      square before resizing, guaranteeing exactly ``target_size``×``target_size``
      output (e.g. 1000×1000) regardless of threshold or original aspect.
    * Then if *target_size* >0 (and resize is enabled in *config*) and the
      (possibly cropped) image is not already *target_size* x *target_size*,
      resize with LANCZOS to that square.

    Returns True when a new file was written to *dst_path*, False when no
    changes were needed or on error. Errors are handled gracefully.
    """
    if not HAS_PIL:
        return False
    if not src_path or not dst_path:
        return False
    try:
        try:
            thr = float(crop_threshold) if crop_threshold is not None else 0.05
        except (TypeError, ValueError):
            thr = 0.05
        thr = max(0.0, min(0.5, thr))
        try:
            tsize = int(target_size) if target_size else 0
        except (TypeError, ValueError):
            tsize = 0
        tsize = max(0, min(4000, tsize))
        # Respect global toggle inside helper as well
        resize_enabled = tsize > 0
        if config is not None and not config.get("cover_resize_enabled", False):
            resize_enabled = False
            # still allow crop even when resize disabled
        try:
            with Image.open(src_path) as img:
                try:
                    img.load()
                except Exception:
                    pass
                w, h = img.size
                if w <= 0 or h <= 0:
                    return False
                need_crop = False
                if crop_enabled and thr >= 0:
                    try:
                        ratio = w / h if h != 0 else 1.0
                    except Exception:
                        ratio = 1.0
                    deviation = abs(ratio - 1.0)
                    if deviation > thr:
                        need_crop = True
                # Force exact size: when resize is wanted, ensure we will crop
                # (if not already) to meet the threshold — but do NOT force
                # automatically to 1:1; crop just enough to bring deviation
                # within thr (user request: crop to threshold, not to square).
                # The threshold already controls how square it must be.
                force_exact = bool(config.get("cover_force_exact_size", False)) if config else False
                if force_exact and resize_enabled and tsize > 0 and w != h:
                    # Only force crop if still outside threshold (not unconditional to square)
                    try:
                        ratio_f = w / h if h else 1.0
                        if abs(ratio_f - 1.0) > thr:
                            need_crop = True
                    except Exception:
                        need_crop = True
                # Never upscale: only downscale if larger than target
                need_resize = False
                if resize_enabled and tsize > 0:
                    if not need_crop:
                        if w > tsize or h > tsize:
                            need_resize = True
                    else:
                        sq = min(w, h)
                        if sq > tsize:
                            need_resize = True
                        # if square already <= target, keep cropped square as-is (no upscale)
                    # Force exact also needs resize if square side != target even when
                    # no crop was otherwise needed but the image is not square — the
                    # crop above already set need_crop, so the square branch applies.
                if not need_crop and not need_resize:
                    return False
                img_to_save = img
                if need_crop:
                    # Crop to threshold, not to square: reduce longer side just enough
                    # to bring |w/h -1| <= thr. For w>h, new_w = int(h*(1+thr)); for h>w, new_h = int(w*(1+thr)).
                    try:
                        if w > h:
                            target_w = int(h * (1.0 + thr))
                            target_w = max(h, min(target_w, w))
                            left = (w - target_w) // 2
                            top = 0
                            right = left + target_w
                            bottom = h
                        else:
                            target_h = int(w * (1.0 + thr))
                            target_h = max(w, min(target_h, h))
                            left = 0
                            top = (h - target_h) // 2
                            right = w
                            bottom = top + target_h
                    except Exception:
                        # Fallback to square on error
                        if w > h:
                            left = (w - h) // 2
                            top = 0
                            right = left + h
                            bottom = h
                        else:
                            left = 0
                            top = (h - w) // 2
                            right = w
                            bottom = top + w
                    try:
                        img_to_save = img.crop((left, top, right, bottom))
                    except Exception:
                        return False
                    w, h = img_to_save.size
                if need_resize:
                    try:
                        try:
                            resample = Image.Resampling.LANCZOS
                        except AttributeError:
                            resample = Image.LANCZOS
                        img_to_save = img_to_save.resize((tsize, tsize), resample)
                    except Exception:
                        try:
                            img_to_save = img_to_save.resize((tsize, tsize), Image.LANCZOS)
                        except Exception:
                            return False
                    w, h = img_to_save.size
                ext_dst = os.path.splitext(dst_path)[1].lower()
                save_kwargs = {}
                dst_dir = os.path.dirname(dst_path)
                if dst_dir and not os.path.exists(dst_dir):
                    try:
                        os.makedirs(dst_dir, exist_ok=True)
                    except OSError:
                        pass
                try:
                    if ext_dst in (".jpg", ".jpeg"):
                        if img_to_save.mode in ("RGBA", "LA", "P"):
                            if img_to_save.mode == "P":
                                try:
                                    img_to_save = img_to_save.convert("RGBA")
                                except Exception:
                                    pass
                            if img_to_save.mode in ("RGBA", "LA"):
                                try:
                                    bg = Image.new("RGB", img_to_save.size, (255, 255, 255))
                                    if img_to_save.mode == "LA":
                                        img_to_save = img_to_save.convert("RGBA")
                                    bg.paste(img_to_save, mask=img_to_save.split()[-1])
                                    img_to_save = bg
                                except Exception:
                                    img_to_save = img_to_save.convert("RGB")
                            else:
                                img_to_save = img_to_save.convert("RGB")
                        elif img_to_save.mode != "RGB":
                            try:
                                img_to_save = img_to_save.convert("RGB")
                            except Exception:
                                pass
                        save_kwargs["format"] = "JPEG"
                        save_kwargs["quality"] = 95
                        save_kwargs["optimize"] = True
                        try:
                            save_kwargs["subsampling"] = 0
                        except Exception:
                            pass
                    elif ext_dst == ".png":
                        save_kwargs["format"] = "PNG"
                        save_kwargs["optimize"] = True
                    elif ext_dst == ".jxl":
                        # Pillow JXL plugin may not be available; fallback to PNG
                        try:
                            save_kwargs["format"] = "JPEGXL"
                        except Exception:
                            save_kwargs["format"] = "PNG"
                            save_kwargs["optimize"] = True
                    else:
                        save_kwargs["format"] = "PNG"
                        save_kwargs["optimize"] = True
                    img_to_save.save(dst_path, **save_kwargs)
                    if img_to_save is not img:
                        try:
                            img_to_save.close()
                        except Exception:
                            pass
                    return True
                except Exception:
                    return False
        except Exception:
            return False
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
    # Support optional config for cover resize/crop (backwards compatible)
    if isinstance(args, (list, tuple)) and len(args) == 11:
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
            config,
        ) = args
    else:
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
        config = None
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
            # If cover resize/crop would modify this JXL, don't skip
            _cover_needs = False
            if config is not None and HAS_PIL:
                try:
                    per_en = True
                    if ext in (".jpg", ".jpeg"):
                        per_en = bool(config.get("cover_jpeg_enabled", True))
                    elif ext == ".png":
                        per_en = bool(config.get("cover_png_enabled", True))
                    elif ext == ".jxl":
                        per_en = bool(config.get("cover_jxl_enabled", True))
                    if per_en:
                        re_en = bool(config.get("cover_resize_enabled", False))
                        cr_en = bool(config.get("cover_crop_enabled", False))
                        tgt = _get_cover_target_size(ext, config) if re_en else 0
                        if (re_en and tgt > 0) or cr_en:
                            # Need to inspect actual dimensions to decide if update needed
                            try:
                                with Image.open(src_path) as _im:
                                    _w, _h = _im.size
                                    force_exact = bool(config.get("cover_force_exact_size", False))
                                    if cr_en:
                                        _ratio = _w / _h if _h else 1.0
                                        if abs(_ratio - 1.0) > float(config.get("cover_crop_threshold", 0.05) or 0.05):
                                            _cover_needs = True
                                    if force_exact and re_en and tgt > 0 and _w != _h:
                                        _cover_needs = True
                                    if re_en and tgt > 0 and (_w > tgt or _h > tgt):
                                        _cover_needs = True
                            except Exception:
                                # If we can't inspect, assume needs re-encode when enabled
                                _cover_needs = True
                except Exception:
                    pass
            if not _cover_needs:
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
            # Streamlined: alpha + cover crop/resize in one Pillow pass when either is needed
            if HAS_PIL and (remove_alpha or (config is not None and (config.get("cover_crop_enabled") or config.get("cover_resize_enabled")))):
                has_alpha = _png_has_alpha(src_path) if remove_alpha else False
                # Check if cover handling would be needed (peek, don't open twice)
                cover_needed = False
                if config is not None:
                    per_en = bool(config.get("cover_png_enabled", True)) if ext == ".png" else True
                    if per_en and (config.get("cover_resize_enabled") or config.get("cover_crop_enabled")):
                        try:
                            with Image.open(src_path) as _im:
                                _w, _h = _im.size
                                if config.get("cover_crop_enabled") and abs(_w/_h - 1.0) > float(config.get("cover_crop_threshold", 0.05) or 0.05):
                                    cover_needed = True
                                if config.get("cover_resize_enabled") and _get_cover_target_size(ext, config) > 0 and (_w > _get_cover_target_size(ext, config) or _h > _get_cover_target_size(ext, config)):
                                    cover_needed = True
                        except Exception:
                            cover_needed = True
                if has_alpha or cover_needed:
                    streamlined_tmp = src_path + ".streamlined.tmp.png"
                    _safe_remove(streamlined_tmp)
                    temp_files.append(streamlined_tmp)
                    if _prepare_image_streamlined(src_path, streamlined_tmp, config, remove_alpha=has_alpha):
                        input_for_cjxl = streamlined_tmp
                    else:
                        _safe_remove(streamlined_tmp)
                        temp_files.remove(streamlined_tmp)
                        # Fallback to old separate handling if streamlined fails
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
                    # PNG-JXL that this djxl cannot decode (e.g. newer encoding) — don't count as failure,
                    # just skip with a warning so the progress doesn't show 1 failed for a valid cover.
                    return (src_path, "skipped", 0, 0, f"skipped (cannot decode JXL: {err[:80]})")

                input_for_cjxl = decoded_png

                if remove_alpha and HAS_PIL:
                    has_alpha = _png_has_alpha(decoded_png)
                    if has_alpha:
                        flat_png = decoded_png + ".no_alpha.png"
                        temp_files.append(flat_png)

                        if _flatten_png_alpha(decoded_png, flat_png):
                            input_for_cjxl = flat_png

        # Cover resize / crop (before cjxl) — uses temp copy to keep original safe
        if config is not None and HAS_PIL:
            try:
                # Determine if cover handling should be attempted
                # Use input_for_cjxl extension for target, but also respect src ext
                ext_for_cover = os.path.splitext(input_for_cjxl)[1].lower()
                if not ext_for_cover:
                    ext_for_cover = ext
                per_enabled = True
                if ext_for_cover in (".jpg", ".jpeg"):
                    per_enabled = bool(config.get("cover_jpeg_enabled", True))
                elif ext_for_cover == ".png":
                    per_enabled = bool(config.get("cover_png_enabled", True))
                elif ext_for_cover == ".jxl":
                    per_enabled = bool(config.get("cover_jxl_enabled", True))
                if per_enabled:
                    resize_enabled_cfg = bool(config.get("cover_resize_enabled", False))
                    crop_enabled_cfg = bool(config.get("cover_crop_enabled", False))
                    crop_thr_cfg = float(config.get("cover_crop_threshold", 0.05) or 0.05)
                    target_for_cover = _get_cover_target_size(ext_for_cover, config) if resize_enabled_cfg else 0
                    # Also handle fallback to src ext target if input is decoded temp with different ext
                    if target_for_cover == 0 and resize_enabled_cfg and ext_for_cover != ext:
                        alt_target = _get_cover_target_size(ext, config)
                        if alt_target > 0:
                            target_for_cover = alt_target
                    if (resize_enabled_cfg and target_for_cover > 0) or crop_enabled_cfg:
                        # Use a dedicated temp to avoid clobbering input_for_cjxl
                        resized_cover_tmp = input_for_cjxl + ".cover_resized.tmp" + ext_for_cover
                        _safe_remove(resized_cover_tmp)
                        did_resize = _resize_and_crop_image(
                            input_for_cjxl, resized_cover_tmp,
                            target_for_cover if resize_enabled_cfg else 0,
                            crop_enabled_cfg, crop_thr_cfg, config
                        )
                        if did_resize and os.path.exists(resized_cover_tmp) and os.path.getsize(resized_cover_tmp) > 0:
                            temp_files.append(resized_cover_tmp)
                            input_for_cjxl = resized_cover_tmp
                            log(f"[cover] resized/cropped {os.path.basename(src_path)} -> {target_for_cover}x{target_for_cover}" if resize_enabled_cfg and target_for_cover else f"[cover] cropped {os.path.basename(src_path)}")
                        else:
                            _safe_remove(resized_cover_tmp)
            except Exception as e:
                log(f"[cover warn] {src_path}: {e}")

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

        # Secure the new file at its final path FIRST (atomic overwrite),
        # then remove the source. If the rename fails, the original is
        # still intact and the finally block cleans up the temp output.
        try:
            os.replace(temp_out_path, final_out_path)
        except OSError as e:
            return (src_path, "failed", 0, 0, f"Couldn't rename: {e}")

        if os.path.normpath(src_path) != os.path.normpath(final_out_path):
            try:
                os.remove(src_path)
            except OSError as e:
                log(f"[cleanup warn] could not remove {src_path}: {e}")

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
    if isinstance(args, (list, tuple)) and len(args) == 8:
        (jpegtran_exe, ljt_version, filepath, force, rename_to_cover,
         progressive, enc, config) = args
    else:
        (jpegtran_exe, ljt_version, filepath, force, rename_to_cover,
         progressive, enc) = args
        config = None
    enabled = enc.get("jpeg") or {}

    filename = os.path.basename(filepath)
    temp_path = filepath + ".opttmp.jpg"
    _cover_resized_tmp = None
    _input_for_jpegtran = filepath

    try:
        original_size = os.path.getsize(filepath)
    except OSError as e:
        return (filename, "failed", 0, 0, f"cannot stat: {e}")

    existing_dest_size = 0
    if rename_to_cover:
        cover_path = os.path.join(os.path.dirname(filepath), "cover.jpg")
        existing_dest_size = _existing_size(cover_path, filepath)

    # Cover-aware skip: don't skip if cover resize/crop needed
    _cover_needs = False
    if not force and config is not None and HAS_PIL:
        try:
            ext_cov = os.path.splitext(filepath)[1].lower()
            per_en = True
            if ext_cov in (".jpg", ".jpeg"):
                per_en = bool(config.get("cover_jpeg_enabled", True))
            elif ext_cov == ".png":
                per_en = bool(config.get("cover_png_enabled", True))
            elif ext_cov == ".jxl":
                per_en = bool(config.get("cover_jxl_enabled", True))
            if per_en:
                re_en = bool(config.get("cover_resize_enabled", False))
                cr_en = bool(config.get("cover_crop_enabled", False))
                tgt_cov = _get_cover_target_size(ext_cov, config) if re_en else 0
                if (re_en and tgt_cov > 0) or cr_en:
                    try:
                        with Image.open(filepath) as _im:
                            _w, _h = _im.size
                            force_exact_j = bool(config.get("cover_force_exact_size", False))
                            if cr_en:
                                _ratio = _w / _h if _h else 1.0
                                if abs(_ratio - 1.0) > float(config.get("cover_crop_threshold", 0.05) or 0.05):
                                    _cover_needs = True
                            if force_exact_j and re_en and tgt_cov > 0 and _w != _h:
                                _cover_needs = True
                            if re_en and tgt_cov > 0 and (_w > tgt_cov or _h > tgt_cov):
                                _cover_needs = True
                    except Exception:
                        _cover_needs = True
        except Exception:
            pass
    if not force and not _cover_needs:
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

    # Cover resize / crop via Pillow before jpegtran (temp copy to keep original safe)
    _cover_resized_tmp = None
    _input_for_jpegtran = filepath
    if config is not None and HAS_PIL:
        try:
            ext_cov = os.path.splitext(filepath)[1].lower()
            per_en = True
            if ext_cov in (".jpg", ".jpeg"):
                per_en = bool(config.get("cover_jpeg_enabled", True))
            elif ext_cov == ".png":
                per_en = bool(config.get("cover_png_enabled", True))
            elif ext_cov == ".jxl":
                per_en = bool(config.get("cover_jxl_enabled", True))
            if per_en:
                re_en = bool(config.get("cover_resize_enabled", False))
                cr_en = bool(config.get("cover_crop_enabled", False))
                thr_cov = float(config.get("cover_crop_threshold", 0.05) or 0.05)
                tgt_cov = _get_cover_target_size(ext_cov, config) if re_en else 0
                if (re_en and tgt_cov > 0) or cr_en:
                    _cover_resized_tmp = filepath + ".cover_resized.tmp.jpg"
                    _safe_remove(_cover_resized_tmp)
                    did = _resize_and_crop_image(filepath, _cover_resized_tmp, tgt_cov if re_en else 0, cr_en, thr_cov, config)
                    if did and os.path.exists(_cover_resized_tmp) and os.path.getsize(_cover_resized_tmp) > 0:
                        _input_for_jpegtran = _cover_resized_tmp
                        log(f"[cover] resized/cropped {os.path.basename(filepath)} -> {tgt_cov}x{tgt_cov}" if re_en and tgt_cov else f"[cover] cropped {os.path.basename(filepath)}")
                    else:
                        _safe_remove(_cover_resized_tmp)
                        _cover_resized_tmp = None
                        _input_for_jpegtran = filepath
        except Exception as e:
            log(f"[cover warn] {filepath}: {e}")
            if _cover_resized_tmp:
                _safe_remove(_cover_resized_tmp)
                _cover_resized_tmp = None
            _input_for_jpegtran = filepath

    cmd = [
        jpegtran_exe,
        "-copy", "none",
        "-optimize",
    ]
    if progressive:
        cmd.append("-progressive")
    cmd.extend(["-outfile", temp_path, _input_for_jpegtran])

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
        try:
            _safe_remove(_cover_resized_tmp)
        except Exception:
            pass


def _process_png_in_place(args):
    if isinstance(args, (list, tuple)) and len(args) == 9:
        (
            oxipng_exe,
            oxipng_version,
            filepath,
            force,
            rename_to_cover,
            remove_alpha,
            optimization_level,
            enc,
            config,
        ) = args
    else:
        (
            oxipng_exe,
            oxipng_version,
            filepath,
            force,
            rename_to_cover,
            remove_alpha,
            optimization_level,
            enc,
        ) = args
        config = None
    enabled = enc.get("png") or {}

    filename = os.path.basename(filepath)
    temp_path = filepath + ".opttmp.png"
    _cover_resized_tmp = None
    _input_for_oxipng = filepath

    try:
        original_size = os.path.getsize(filepath)
    except OSError as e:
        return (filename, "failed", 0, 0, f"cannot stat: {e}")

    existing_dest_size = 0
    if rename_to_cover:
        cover_path = os.path.join(os.path.dirname(filepath), "cover.png")
        existing_dest_size = _existing_size(cover_path, filepath)

    # Cover-aware skip check
    _cover_needs = False
    if not force and config is not None and HAS_PIL:
        try:
            ext_cov = os.path.splitext(filepath)[1].lower()
            per_en = True
            if ext_cov in (".jpg", ".jpeg"):
                per_en = bool(config.get("cover_jpeg_enabled", True))
            elif ext_cov == ".png":
                per_en = bool(config.get("cover_png_enabled", True))
            elif ext_cov == ".jxl":
                per_en = bool(config.get("cover_jxl_enabled", True))
            if per_en:
                re_en = bool(config.get("cover_resize_enabled", False))
                cr_en = bool(config.get("cover_crop_enabled", False))
                tgt_cov = _get_cover_target_size(ext_cov, config) if re_en else 0
                if (re_en and tgt_cov > 0) or cr_en:
                    try:
                        with Image.open(filepath) as _im:
                            _w, _h = _im.size
                            force_exact_j = bool(config.get("cover_force_exact_size", False))
                            if cr_en:
                                _ratio = _w / _h if _h else 1.0
                                if abs(_ratio - 1.0) > float(config.get("cover_crop_threshold", 0.05) or 0.05):
                                    _cover_needs = True
                            if force_exact_j and re_en and tgt_cov > 0 and _w != _h:
                                _cover_needs = True
                            if re_en and tgt_cov > 0 and (_w > tgt_cov or _h > tgt_cov):
                                _cover_needs = True
                    except Exception:
                        _cover_needs = True
        except Exception:
            pass
    if not force and not _cover_needs:
        tags = _read_png_text(filepath)
        q = tags.get("ENCODER_QUALITY")
        v = tags.get("ENCODER_VERSION")

        if not _identity_missing(enabled, q, v):
            try:
                if int(q) >= optimization_level and not _version_is_older(v, oxipng_version):
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
        has_alpha = _png_has_alpha(filepath)
        if has_alpha:
            flat_path = filepath + ".no_alpha.png"

            try:
                if _flatten_png_alpha(filepath, flat_path):
                    os.replace(flat_path, filepath)
                else:
                    _safe_remove(flat_path)
            except Exception:
                _safe_remove(flat_path)

    # Cover resize / crop before oxipng (temp copy)
    if config is not None and HAS_PIL:
        try:
            ext_cov = os.path.splitext(filepath)[1].lower()
            per_en = True
            if ext_cov in (".jpg", ".jpeg"):
                per_en = bool(config.get("cover_jpeg_enabled", True))
            elif ext_cov == ".png":
                per_en = bool(config.get("cover_png_enabled", True))
            elif ext_cov == ".jxl":
                per_en = bool(config.get("cover_jxl_enabled", True))
            if per_en:
                re_en = bool(config.get("cover_resize_enabled", False))
                cr_en = bool(config.get("cover_crop_enabled", False))
                thr_cov = float(config.get("cover_crop_threshold", 0.05) or 0.05)
                tgt_cov = _get_cover_target_size(ext_cov, config) if re_en else 0
                if (re_en and tgt_cov > 0) or cr_en:
                    _cover_resized_tmp = filepath + ".cover_resized.tmp.png"
                    _safe_remove(_cover_resized_tmp)
                    did = _resize_and_crop_image(filepath, _cover_resized_tmp, tgt_cov if re_en else 0, cr_en, thr_cov, config)
                    if did and os.path.exists(_cover_resized_tmp) and os.path.getsize(_cover_resized_tmp) > 0:
                        _input_for_oxipng = _cover_resized_tmp
                        log(f"[cover] resized/cropped {os.path.basename(filepath)} -> {tgt_cov}x{tgt_cov}" if re_en and tgt_cov else f"[cover] cropped {os.path.basename(filepath)}")
                    else:
                        _safe_remove(_cover_resized_tmp)
                        _cover_resized_tmp = None
                        _input_for_oxipng = filepath
                else:
                    _input_for_oxipng = filepath
        except Exception as e:
            log(f"[cover warn] {filepath}: {e}")
            if _cover_resized_tmp:
                _safe_remove(_cover_resized_tmp)
                _cover_resized_tmp = None
            _input_for_oxipng = filepath
    else:
        _input_for_oxipng = filepath

    cmd = [
        oxipng_exe,
        "-o", str(optimization_level),
        "--strip", "safe",
        "--force",
        "--output", temp_path,
        _input_for_oxipng,
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
            # If cover resize was applied, ensure temp is cleaned
            if _cover_resized_tmp:
                _safe_remove(_cover_resized_tmp)
            return (filename, "failed", 0, 0, f"oxipng failed: {err}")

        if not os.path.exists(temp_path):
            try:
                shutil.copy2(_input_for_oxipng, temp_path)
            except Exception:
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
                _encoder_dict("oxipng", optimization_level,
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
        try:
            _safe_remove(_cover_resized_tmp)
        except Exception:
            pass


def _process_jxl_in_place(args):
    if isinstance(args, (list, tuple)) and len(args) == 10:
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
            config,
        ) = args
    else:
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
        config = None
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

        # Cover-aware skip
        _cover_needs = False
        if not force and config is not None and HAS_PIL:
            try:
                ext_cov = os.path.splitext(src_path)[1].lower()
                per_en = True
                if ext_cov in (".jpg", ".jpeg"):
                    per_en = bool(config.get("cover_jpeg_enabled", True))
                elif ext_cov == ".png":
                    per_en = bool(config.get("cover_png_enabled", True))
                elif ext_cov == ".jxl":
                    per_en = bool(config.get("cover_jxl_enabled", True))
                if per_en:
                    re_en = bool(config.get("cover_resize_enabled", False))
                    cr_en = bool(config.get("cover_crop_enabled", False))
                    tgt_cov = _get_cover_target_size(ext_cov, config) if re_en else 0
                    if (re_en and tgt_cov > 0) or cr_en:
                        try:
                            with Image.open(src_path) as _im:
                                _w, _h = _im.size
                                force_exact = bool(config.get("cover_force_exact_size", False))
                                if cr_en:
                                    _ratio = _w / _h if _h else 1.0
                                    if abs(_ratio - 1.0) > float(config.get("cover_crop_threshold", 0.05) or 0.05):
                                        _cover_needs = True
                                if force_exact and re_en and tgt_cov > 0 and _w != _h:
                                    _cover_needs = True
                                if re_en and tgt_cov > 0 and (_w > tgt_cov or _h > tgt_cov):
                                    _cover_needs = True
                        except Exception:
                            _cover_needs = True
            except Exception:
                pass
        if not force and not _cover_needs:
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

        # Cover resize / crop on the decoded input before re-encoding
        if config is not None and HAS_PIL and input_for_cjxl:
            try:
                ext_for_cover = os.path.splitext(input_for_cjxl)[1].lower()
                if not ext_for_cover:
                    ext_for_cover = os.path.splitext(src_path)[1].lower()
                per_en = True
                if ext_for_cover in (".jpg", ".jpeg"):
                    per_en = bool(config.get("cover_jpeg_enabled", True))
                elif ext_for_cover == ".png":
                    per_en = bool(config.get("cover_png_enabled", True))
                elif ext_for_cover == ".jxl":
                    per_en = bool(config.get("cover_jxl_enabled", True))
                # Also check src ext per-format as fallback
                src_ext = os.path.splitext(src_path)[1].lower()
                src_per_en = True
                if src_ext in (".jpg", ".jpeg"):
                    src_per_en = bool(config.get("cover_jpeg_enabled", True))
                elif src_ext == ".png":
                    src_per_en = bool(config.get("cover_png_enabled", True))
                elif src_ext == ".jxl":
                    src_per_en = bool(config.get("cover_jxl_enabled", True))
                if per_en or src_per_en:
                    re_en = bool(config.get("cover_resize_enabled", False))
                    cr_en = bool(config.get("cover_crop_enabled", False))
                    thr_cov = float(config.get("cover_crop_threshold", 0.05) or 0.05)
                    tgt_cov = _get_cover_target_size(ext_for_cover, config) if re_en else 0
                    if tgt_cov == 0 and re_en:
                        # fallback to src target
                        tgt_cov = _get_cover_target_size(src_ext, config)
                    if (re_en and tgt_cov > 0) or cr_en:
                        resized_tmp = input_for_cjxl + ".cover_resized.tmp" + ext_for_cover
                        _safe_remove(resized_tmp)
                        did = _resize_and_crop_image(input_for_cjxl, resized_tmp, tgt_cov if re_en else 0, cr_en, thr_cov, config)
                        if did and os.path.exists(resized_tmp) and os.path.getsize(resized_tmp) > 0:
                            temp_files.append(resized_tmp)
                            input_for_cjxl = resized_tmp
                            log(f"[cover] resized/cropped {os.path.basename(src_path)} -> {tgt_cov}x{tgt_cov}" if re_en and tgt_cov else f"[cover] cropped {os.path.basename(src_path)}")
                        else:
                            _safe_remove(resized_tmp)
            except Exception as e:
                log(f"[cover warn] {src_path}: {e}")

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
    if isinstance(args, (list, tuple)) and len(args) == 14:
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
            progressive,
            optimization_level,
            enc,
            config,
        ) = args
    else:
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
            progressive,
            optimization_level,
            enc,
        ) = args
        config = None

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

            # Cover resize / crop before re-encoding JPEG
            if config is not None and HAS_PIL:
                try:
                    out_ext = os.path.splitext(out_path)[1].lower() if out_path else ".jpg"
                    per_en = True
                    if out_ext in (".jpg", ".jpeg"):
                        per_en = bool(config.get("cover_jpeg_enabled", True))
                    elif out_ext == ".png":
                        per_en = bool(config.get("cover_png_enabled", True))
                    elif out_ext == ".jxl":
                        per_en = bool(config.get("cover_jxl_enabled", True))
                    # also check src JXL per-format as fallback
                    src_per_en = bool(config.get("cover_jxl_enabled", True))
                    if per_en or src_per_en:
                        re_en = bool(config.get("cover_resize_enabled", False))
                        cr_en = bool(config.get("cover_crop_enabled", False))
                        thr_cov = float(config.get("cover_crop_threshold", 0.05) or 0.05)
                        tgt_cov = _get_cover_target_size(out_ext, config) if re_en else 0
                        if tgt_cov == 0 and re_en:
                            # fallback to src JXL target if output per-format not set
                            tgt_cov = _get_cover_target_size(".jxl", config)
                        if (re_en and tgt_cov > 0) or cr_en:
                            resized_jpeg = input_file + ".cover_resized.tmp.jpg"
                            _safe_remove(resized_jpeg)
                            did = _resize_and_crop_image(input_file, resized_jpeg, tgt_cov if re_en else 0, cr_en, thr_cov, config)
                            if did and os.path.exists(resized_jpeg) and os.path.getsize(resized_jpeg) > 0:
                                temp_files.append(resized_jpeg)
                                input_file = resized_jpeg
                                log(f"[cover] resized/cropped {os.path.basename(src_path)} -> {tgt_cov}x{tgt_cov}" if re_en and tgt_cov else f"[cover] cropped {os.path.basename(src_path)}")
                            else:
                                _safe_remove(resized_jpeg)
                except Exception as e:
                    log(f"[cover warn] {src_path}: {e}")

            if jpegtran_exe:
                optimized = src_path + ".optimized.jpg"
                temp_files.append(optimized)

                try:
                    jpeg_cmd = [
                        jpegtran_exe,
                        "-copy", "none",
                        "-optimize",
                        "-outfile", optimized,
                        input_file,
                    ]
                    if progressive:
                        jpeg_cmd.insert(4, "-progressive")
                    result = run_tool(
                        jpeg_cmd,
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

            # Secure the decoded output first, then drop the source JXL.
            try:
                os.replace(final_input, out_path)
            except OSError as e:
                return (src_path, "failed", 0, 0, f"Couldn't write output: {e}")

            try:
                os.remove(src_path)
            except OSError as e:
                log(f"[cleanup warn] could not remove {src_path}: {e}")

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
            has_alpha = _png_has_alpha(decoded_png)
            if has_alpha:
                flat_png = decoded_png + ".no_alpha.png"
                temp_files.append(flat_png)

                if _flatten_png_alpha(decoded_png, flat_png):
                    input_file = flat_png

        # Cover resize / crop before re-encoding PNG
        if config is not None and HAS_PIL:
            try:
                out_ext = os.path.splitext(out_path)[1].lower() if out_path else ".png"
                per_en = True
                if out_ext in (".jpg", ".jpeg"):
                    per_en = bool(config.get("cover_jpeg_enabled", True))
                elif out_ext == ".png":
                    per_en = bool(config.get("cover_png_enabled", True))
                elif out_ext == ".jxl":
                    per_en = bool(config.get("cover_jxl_enabled", True))
                src_per_en = bool(config.get("cover_jxl_enabled", True))
                if per_en or src_per_en:
                    re_en = bool(config.get("cover_resize_enabled", False))
                    cr_en = bool(config.get("cover_crop_enabled", False))
                    thr_cov = float(config.get("cover_crop_threshold", 0.05) or 0.05)
                    tgt_cov = _get_cover_target_size(out_ext, config) if re_en else 0
                    if tgt_cov == 0 and re_en:
                        tgt_cov = _get_cover_target_size(".jxl", config)
                    if (re_en and tgt_cov > 0) or cr_en:
                        resized_png = input_file + ".cover_resized.tmp.png"
                        _safe_remove(resized_png)
                        did = _resize_and_crop_image(input_file, resized_png, tgt_cov if re_en else 0, cr_en, thr_cov, config)
                        if did and os.path.exists(resized_png) and os.path.getsize(resized_png) > 0:
                            temp_files.append(resized_png)
                            input_file = resized_png
                            log(f"[cover] resized/cropped {os.path.basename(src_path)} -> {tgt_cov}x{tgt_cov}" if re_en and tgt_cov else f"[cover] cropped {os.path.basename(src_path)}")
                        else:
                            _safe_remove(resized_png)
            except Exception as e:
                log(f"[cover warn] {src_path}: {e}")

        if oxipng_exe:
            optimized = src_path + ".optimized.png"
            temp_files.append(optimized)

            try:
                result = run_tool(
                    [
                        oxipng_exe,
                        "-o", str(optimization_level),
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

        # Secure the decoded output first, then drop the source JXL.
        try:
            os.replace(final_input, out_path)
        except OSError as e:
            return (src_path, "failed", 0, 0, f"Couldn't write output: {e}")

        try:
            os.remove(src_path)
        except OSError as e:
            log(f"[cleanup warn] could not remove {src_path}: {e}")

        try:
            _strip_png_metadata(out_path)
        except Exception:
            pass

        if oxipng_exe:
            enc_ver = oxipng_version
            program = "oxipng"
            quality = optimization_level
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
    progressive = config.get("jpeg_progressive", True)
    optimization_level = config.get("png_optimization_level",
                                    PNG_OPTIMIZATION_LEVEL)
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

    if convert_jxl_back:
        mode = "JXL -> original (reverse only; other files untouched)"
    elif reencode_to_jxl:
        mode = f"JPEG XL conversion (effort {effort})"
    else:
        mode = "Lossless in-place JPEG/PNG/JXL"

    log(f"mode: {mode}")
    log(f"target: {target_dir}")

    targets = config.get("targets")
    files = _collect_targets(targets, VALID_EXTENSIONS)
    if targets is None:
        files = sorted(_walk_files(target_dir, VALID_EXTENSIONS))

    log(f"found {len(files)} image file(s) for processing")
    for f in files[:10]:
        log(f"  - {os.path.relpath(f, target_dir) if target_dir in f else f}")
    if len(files) > 10:
        log(f"  ... and {len(files)-10} more")

    if not files:
        log("No image files found.")
        return stats

    cpu_count = os.cpu_count() or 1
    est_workers = worker_count(config, default=cpu_count, items=len(files))
    threads_per_file = max(1, cpu_count // max(1, est_workers))

    # With rename_to_cover, at most ONE image per folder may take the cover
    # name; every other image keeps its own basename. Otherwise front/back/
    # booklet scans would all write to the same cover.* file and clobber
    # each other (losing every image but the last).
    cover_map = {}
    if rename_to_cover:
        groups = {}
        for f in files:
            groups.setdefault(os.path.dirname(f), []).append(f)
        for folder, group in groups.items():
            def _cover_key(f):
                base = os.path.splitext(os.path.basename(f).lower())[0]
                return (0 if base in ("cover", "front", "folder") else 1,
                        os.path.basename(f).lower(), f)
            cover_map[folder] = sorted(group, key=_cover_key)[0]

    def _renames(f):
        return rename_to_cover and f == cover_map.get(os.path.dirname(f))

    tasks = []

    for f in files:
        ext = os.path.splitext(f)[1].lower()

        if convert_jxl_back:
            # Reverse mode is EXCLUSIVE: only .jxl files are converted back
            # to their original format; other files are left untouched. This
            # prevents the endless .jpg/.png <-> .jxl alternation on re-runs.
            if ext == ".jxl":
                tasks.append((
                    _process_jxl_back_to_original,
                    (
                        djxl_path,
                        ljt["jpegtran_exe"] if ljt else None,
                        ljt["version"] if ljt else None,
                        ox["oxipng_exe"] if ox else None,
                        ox["version"] if ox else None,
                        f,
                        _renames(f),
                        remove_alpha,
                        HAS_PIL,
                        force,
                        progressive,
                        optimization_level,
                        enc,
                        config,
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
                    _renames(f),
                    remove_alpha,
                    enc,
                    config,
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
                            _renames(f),
                            progressive,
                            enc,
                            config,
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
                            _renames(f),
                            remove_alpha,
                            optimization_level,
                            enc,
                            config,
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
                        _renames(f),
                        enc,
                        config,
                    ),
                    f,
                ))

    log(f"prepared {len(tasks)} task(s) from {len(files)} file(s) (mode: {mode})")
    if not tasks:
        log(f"No active image tasks after skips ({stats['skipped_count']} skipped).")
        return stats

    workers = worker_count(config, default=cpu_count, items=len(tasks))
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

