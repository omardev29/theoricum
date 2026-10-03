"""Countdown (exam) or elapsed time (other modes) shown in the top-right corner."""

import math

from textual.widgets import Digits

WARNING_S = 5 * 60
DANGER_S = 60


def format_seconds(seconds: float, *, round_up: bool = False) -> str:
    total = max(0, math.ceil(seconds) if round_up else int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


class Clock(Digits):
    def show(self, *, remaining: float | None, elapsed: float) -> None:
        if remaining is None:
            self.update(format_seconds(elapsed))
            self.set_class(False, "-warning", "-danger")
            return
        self.update(format_seconds(remaining, round_up=True))
        self.set_class(DANGER_S < remaining <= WARNING_S, "-warning")
        self.set_class(remaining <= DANGER_S, "-danger")
