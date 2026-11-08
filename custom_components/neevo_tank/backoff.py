"""Slow down repeated sign-in attempts after a failed setup.

Home Assistant retries a failed setup as often as about every 80 seconds, and that
timing can't be changed. A rejected password can look like a server error, so those
retries could look like password guessing and put the account at risk. While waiting,
a retry ends here without contacting Nee-Vo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SETUP_RETRY_FIRST_WAIT, SETUP_RETRY_LONGEST_WAIT


@dataclass
class SetupBackoff:
    """The failed setup attempts for one account."""

    failures: int
    next_attempt: datetime


def _backoffs(hass: HomeAssistant) -> dict[str, SetupBackoff]:
    """Return the back-off state, which lasts until Home Assistant restarts."""
    return hass.data.setdefault(DOMAIN, {})


def should_wait(hass: HomeAssistant, entry_id: str) -> bool:
    """Return whether this account must wait before contacting Nee-Vo again."""
    backoff = _backoffs(hass).get(entry_id)
    return backoff is not None and dt_util.utcnow() < backoff.next_attempt


def record_failure(hass: HomeAssistant, entry_id: str) -> None:
    """Record a failed attempt, doubling the wait up to the longest allowed."""
    backoffs = _backoffs(hass)
    previous = backoffs.get(entry_id)
    failures = previous.failures + 1 if previous else 1
    wait = min(
        SETUP_RETRY_FIRST_WAIT * 2 ** (failures - 1), SETUP_RETRY_LONGEST_WAIT
    )
    backoffs[entry_id] = SetupBackoff(failures, dt_util.utcnow() + wait)


def clear(hass: HomeAssistant, entry_id: str) -> None:
    """Forget failed attempts, so the next attempt can run right away."""
    _backoffs(hass).pop(entry_id, None)
