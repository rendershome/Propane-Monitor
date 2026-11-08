"""Work out propane consumption from a tank's level history.

Tank levels drift up and down with temperature, so adding every small drop would
count propane that was never burned. This tracks the lowest level since the last
refill, and only counts a fall below it that is larger than normal noise.

Work is done in percent, so a change to the tank's capacity cannot create a false
jump in the total. Thresholds were chosen from one tank's history, where the
largest daily rise without a refill was 0.3%.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

# A fall smaller than this, in percent, is treated as noise until it grows.
DROP_DEADBAND_PCT = 0.5
# A rise of at least this, in percent, is treated as a refill.
REFILL_RISE_PCT = 5.0


@dataclass
class MeterState:
    """The running state of a tank's consumption meter."""

    total_l: float = 0.0
    watermark_pct: float | None = None
    last_date: datetime | None = None
    last_refill: datetime | None = None


def advance(
    state: MeterState,
    readings: Iterable[tuple[datetime, float]],
    capacity_l: float | None,
) -> None:
    """Add any readings newer than the last one processed, oldest first."""
    for date, level in readings:
        if state.last_date is not None and date <= state.last_date:
            continue
        state.last_date = date
        if state.watermark_pct is None:
            state.watermark_pct = level
            continue

        if level - state.watermark_pct >= REFILL_RISE_PCT:
            state.watermark_pct = level
            state.last_refill = date
        elif state.watermark_pct - level >= DROP_DEADBAND_PCT:
            if capacity_l:
                state.total_l += (state.watermark_pct - level) / 100 * capacity_l
            state.watermark_pct = level


def start_meter(readings: list[tuple[datetime, float]]) -> MeterState:
    """Start a meter at zero, finding the latest refill in the existing history.

    Past usage is not added to the total, so the meter does not begin with a jump.
    """
    state = MeterState()
    advance(state, readings, None)
    state.total_l = 0.0
    return state


def consumed_over(
    readings: list[tuple[datetime, float]], capacity_l: float | None
) -> float:
    """Return the liters consumed across a list of readings."""
    state = MeterState()
    advance(state, readings, capacity_l)
    return state.total_l
