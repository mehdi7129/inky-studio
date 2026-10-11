"""Select frontend bytes without coupling their location to a wheel install."""
from __future__ import annotations

from pathlib import Path

from inky_web.provisioning.factory_environment import factory_signals_present

FACTORY_CLIENT_DIST = Path("/usr/lib/inky-studio/client/dist")


def resolve_client_dist(module_file: str | Path) -> Path:
    """Keep the installed factory path even if the bundle is incomplete.

    Factory admission belongs to the startup guard. Selecting frontend files
    must never conceal an incomplete factory install by serving source bytes.
    Legacy source and editable installations retain their existing layout.
    """
    if factory_signals_present():
        return FACTORY_CLIENT_DIST
    return Path(module_file).resolve().parents[2] / "client" / "dist"
