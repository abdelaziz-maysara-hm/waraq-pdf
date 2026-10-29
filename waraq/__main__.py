import os
import sys


def _gui_files(args):
    """PDF paths given on the command line (double-click / "Open with")."""
    if not args:
        return []
    if all(a.lower().endswith(".pdf") and os.path.isfile(a) for a in args):
        return args
    return None


def run():
    files = _gui_files(sys.argv[1:])
    if files is None:
        from .cli import main
        raise SystemExit(main())
    from .gui.app import main as gui_main
    gui_main(files)


if __name__ == "__main__":
    run()
