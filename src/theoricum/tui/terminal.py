"""Run before importing textual-image: its import-time terminal probe divides by the window size,
which crashes (ZeroDivisionError) on ptys that report 0×0, e.g. under `script` or some CI.
"""

import logging

logger = logging.getLogger(__name__)


def guard_image_probe() -> None:
    """Pre-seed textual-image's probe cache with safe defaults when the window size is unknown."""
    from textual_image import _terminal

    try:
        rows, columns, *_ = _terminal.get_tiocgwinsz()
    except OSError:
        return
    if rows and columns:
        return
    logger.debug("terminal reports a 0x0 window; skipping the textual-image probe")
    _terminal.probe_terminal._result = _terminal.TerminalCapabilities(  # type: ignore[attr-defined]
        _terminal.CellSize(10, 20), sixel=False, tgp=False
    )
