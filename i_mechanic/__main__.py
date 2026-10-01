"""Launch the I, Mechanic desktop application."""
import sys

from .desktop.qt_app import main as qt_main


def main():
    return qt_main()


if __name__ == "__main__":
    sys.exit(main())