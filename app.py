"""Compatibility launcher; prefer ``python -m i_mechanic``."""

import sys

from i_mechanic.__main__ import main


def load_coach_module():
    """Keep the previous coach-loader API available to local scripts."""
    from i_mechanic import coach

    return coach


if __name__ == "__main__":
    sys.exit(main())