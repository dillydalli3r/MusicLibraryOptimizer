#!/usr/bin/env python3
"""Music Library Optimizer - command line entry point.

Built into mlo.exe (console subsystem) by PyInstaller. Run with no
arguments for the command overview; `mlo menu` opens the interactive
console menu; `mlo install --user|--system` puts this CLI on PATH.
"""
import sys


def main():
    from mlo.cliapp import main as cli_main
    try:
        sys.exit(cli_main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)


if __name__ == "__main__":
    main()
