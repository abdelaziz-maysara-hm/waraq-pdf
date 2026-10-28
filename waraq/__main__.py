import sys


def run():
    if len(sys.argv) > 1:
        from .cli import main
        raise SystemExit(main())
    from .gui.app import main as gui_main
    gui_main()


if __name__ == "__main__":
    run()
