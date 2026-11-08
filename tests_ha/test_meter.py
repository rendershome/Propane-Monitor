"""Tests for the consumption meter."""

from datetime import UTC, datetime, timedelta

from custom_components.neevo_tank.meter import (
    MeterState,
    advance,
    consumed_over,
    start_meter,
)

START = datetime(2026, 8, 1, tzinfo=UTC)


def days(*levels):
    """Build one reading per day."""
    return [(START + timedelta(days=i), level) for i, level in enumerate(levels)]


def test_counts_real_drops():
    assert consumed_over(days(50, 49, 48), 1000) == 20


def test_noise_is_not_counted():
    """Wobbling around one level must not add up to phantom consumption."""
    assert consumed_over(days(50, 49.8, 50, 49.8, 50, 49.8, 50), 1000) == 0


def test_small_falls_count_once_they_add_up():
    assert round(consumed_over(days(50, 49.8, 49.6, 49.4), 1000), 6) == 6


def test_rise_without_refill_does_not_recount():
    """A warm spell that rises and falls back burned nothing."""
    assert consumed_over(days(50, 52, 50), 1000) == 0


def test_refill_is_recorded_and_not_counted():
    state = MeterState()
    readings = days(20, 80, 79)
    advance(state, readings, 1000)
    assert state.last_refill == readings[1][0]
    assert state.total_l == 10
    assert state.watermark_pct == 79


def test_readings_are_processed_once():
    state = MeterState()
    readings = days(50, 49)
    advance(state, readings, 1000)
    advance(state, readings, 1000)
    assert state.total_l == 10


def test_capacity_change_does_not_create_a_jump():
    state = MeterState()
    advance(state, days(50), 1000)
    advance(state, [(START + timedelta(days=1), 50)], 2000)
    assert state.total_l == 0


def test_start_meter_begins_at_zero_and_finds_refill():
    readings = days(20, 15, 80, 70)
    state = start_meter(readings)
    assert state.total_l == 0
    assert state.last_refill == readings[2][0]
    assert state.watermark_pct == 70
    assert state.last_date == readings[3][0]


def test_empty_history():
    assert consumed_over([], 1000) == 0
    assert start_meter([]).last_date is None
