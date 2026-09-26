"""Compatibility entry point for already-installed ``inky-studio`` wrappers.

The installer copies its wrapper to /usr/local/bin. An in-app update replaces
the application sources, but that older wrapper can still invoke this module.
"""
from inky_web.services.updater import main

if __name__ == "__main__":
    raise SystemExit(main())
