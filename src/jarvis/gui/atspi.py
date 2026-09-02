"""AT-SPI accessibility tree access — optional read layer (ADR-0010).

Uses `pyatspi` when importable (distro package `python3-pyatspi`); absence is
an honest capability gap, never an error and never a blocker for other
backends.
"""

from __future__ import annotations

import importlib.util


def atspi_available() -> bool:
    try:
        return importlib.util.find_spec("pyatspi") is not None
    except (ImportError, ValueError):
        return False


def desktop_window_titles() -> tuple[list[str] | None, str]:
    """Return (titles, reason). titles=None with a reason when unavailable."""
    if not atspi_available():
        return None, "pyatspi not installed (distro package python3-pyatspi)"
    try:
        import pyatspi  # type: ignore[import-not-found]

        desktop = pyatspi.Registry.getDesktop(0)
        titles: list[str] = []
        for app in desktop:
            for frame in app:
                if frame.getRoleName() in ("frame", "dialog", "window"):
                    titles.append(frame.name or "(untitled)")
        return titles, "pyatspi accessibility tree"
    except Exception as exc:
        return None, f"pyatspi present but unavailable: {exc}"
