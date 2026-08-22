#!/usr/bin/env python3
"""
Music Library Optimizer — Desktop Application (v1.1.0)
======================================================
PySide6 (Qt) GUI front-end for the `mlo` core package.

Layout
------
    mlo/            organized core package (all processing logic)
    gui/            PySide6 interface (theme engine, library, dialogs)
    app.py          this GUI entry point
    mlo_cli.py      command-line front-end
    config.json     persisted settings (created on first save)
    .dependencies/  external encoder toolchain (flac, libjxl,
                    libjpeg-turbo, oxipng, AudioAuditor)

Requires:  pip install PySide6 mutagen
Optional:  pip install Pillow tqdm

Run with:  python app.py   (or the compiled Music Library Optimizer.exe)
"""
import sys


def main():
    # Keep tracebacks visible for windowed builds.
    sys.excepthook = _excepthook
    from gui import run
    sys.exit(run() or 0)


def _excepthook(exc_type, exc, tb):
    import traceback
    traceback.print_exception(exc_type, exc, tb)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None, "Unexpected error",
                "".join(traceback.format_exception(exc_type, exc, tb)))
    except Exception:
        pass


if __name__ == "__main__":
    main()
