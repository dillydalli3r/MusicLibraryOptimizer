"""Subprocess wrapper that never flashes console windows.

The GUI runs windowed (pythonw / PyInstaller --windowed), so it owns no
console of its own. On Windows every console executable launched by such a
process would otherwise create its own console window - and with dozens of
encoder threads running, that means a storm of flashing windows during
Run All. Every external tool invocation therefore goes through run_tool(),
which passes CREATE_NO_WINDOW. Output is already captured via pipes, so
nothing is lost.
"""

import os
import subprocess

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def run_tool(*args, **kwargs):
    """Drop-in subprocess.run() that hides child console windows on Windows."""
    kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run(*args, **kwargs)
