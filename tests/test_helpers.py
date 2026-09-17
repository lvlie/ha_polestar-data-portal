"""Unit tests for the value conversion helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from custom_components.polestar_data_portal.const import (
    DAILY_REQUEST_BUDGET,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    estimated_daily_requests,
    recommended_scan_interval_minutes,
)
from custom_components.polestar_data_portal.enums import OPEN_STATUS, SYNC_STATUS
from custom_components.polestar_data_portal.helpers import (
    EnumSpec,
    build_device_names,
    daily_time_to_string,
    iso_to_datetime,
    nested,
    timestamp_to_datetime,
    to_float,
    to_int,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12.5, 12.5),
        ("12.5", 12.5),  # altitude and speed arrive as strings
        (0, 0.0),
        ("0", 0.0),
        (None, None),
        ("", None),
        ("abc", None),
        (True, None),  # a bool is not a reading
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
    ],
)
def test_to_float(value: Any, expected: float | None) -> None:
    """Numbers survive their string encoding; non-numbers become None."""
    assert to_float(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"), [("42", 42), (42.9, 42), (None, None), ("x", None)]
)
def test_to_int(value: Any, expected: int | None) -> None:
    """Integers tolerate string and float encodings."""
    assert to_int(value) == expected


def test_nested_walks_missing_levels_safely() -> None:
    """A missing intermediate key yields None rather than raising."""
    data = {"a": {"b": {"c": 1}}}
    assert nested(data, "a", "b", "c") == 1
    assert nested(data, "a", "missing", "c") is None
    assert nested(data, "a", "b", "c", "too", "deep") is None
    assert nested(None, "a") is None
    assert nested({"a": 5}, "a", "b") is None


def test_timestamp_conversion() -> None:
    """Epoch seconds arrive as a string and include a nanosecond part."""
    result = timestamp_to_datetime({"seconds": "1788362002", "nanos": 500_000_000})
    assert result == datetime.fromtimestamp(1788362002.5, tz=UTC)


@pytest.mark.parametrize(
    "value",
    [
        {"seconds": "0", "nanos": 0},  # "never happened"
        {"seconds": 0},
        {"nanos": 5},
        {},
        None,
        "not-a-timestamp",
    ],
)
def test_unset_timestamps_are_none(value: Any) -> None:
    """An unset timestamp must not become 1970-01-01."""
    assert timestamp_to_datetime(value) is None


@pytest.mark.parametrize(
    ("value", "expected_year"),
    [
        ("2026-09-17T10:30:00Z", 2026),
        ("2026-09-17T10:30:00+02:00", 2026),
        ("2026-09-17T10:30:00", 2026),  # naive input is treated as UTC
    ],
)
def test_iso_parsing(value: str, expected_year: int) -> None:
    """ISO 8601 strings are parsed into aware datetimes."""
    parsed = iso_to_datetime(value)
    assert parsed is not None
    assert parsed.year == expected_year
    assert parsed.tzinfo is not None


@pytest.mark.parametrize("value", ["", None, "yesterday", 42])
def test_bad_iso_values_are_none(value: Any) -> None:
    """An unparseable timestamp is reported as unknown."""
    assert iso_to_datetime(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"hour": 7, "minute": 5}, "07:05"),
        ({"hour": 0, "minute": 0}, "00:00"),
        ({"hour": 23, "minute": 59}, "23:59"),
        # The API omits whichever component is zero, so a timer set on the
        # hour arrives without a minute. Seen on a real vehicle.
        ({"hour": 7}, "07:00"),
        ({"minute": 30}, "00:30"),
        ({}, None),
        (None, None),
    ],
)
def test_daily_time_formatting(value: Any, expected: str | None) -> None:
    """Timer times are rendered as zero-padded HH:MM."""
    assert daily_time_to_string(value) == expected


def test_enum_options_exclude_placeholders() -> None:
    """UNSPECIFIED, UNDEFINED and UNKNOWN members are not real states."""
    assert "unspecified" not in OPEN_STATUS.options
    assert OPEN_STATUS.options == ["open", "closed", "ajar"]
    # SYNC_STATUS has no shared prefix and one UNKNOWN member.
    assert "sync_status_unknown" not in SYNC_STATUS.options
    assert "synced" in SYNC_STATUS.options


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("OPEN_STATUS_OPEN", "open"),
        ("OPEN_STATUS_UNSPECIFIED", None),
        ("OPEN_STATUS_TELEPORTED", None),  # added upstream, unknown here
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_enum_mapping(raw: Any, expected: str | None) -> None:
    """Only published members map to a state."""
    assert OPEN_STATUS.to_option(raw) == expected


def test_enum_without_a_prefix() -> None:
    """Enums whose members share no prefix still work."""
    spec = EnumSpec(prefix="", values=("UNSPECIFIED", "MONDAY", "TUESDAY"))
    assert spec.options == ["monday", "tuesday"]
    assert spec.to_option("MONDAY") == "monday"


@pytest.mark.parametrize("requests_per_poll", [1, 15, 30, 60, 150, 600])
def test_recommended_interval_fits_the_budget(requests_per_poll: int) -> None:
    """The recommended interval never plans to exceed the daily allowance."""
    minutes = recommended_scan_interval_minutes(requests_per_poll)
    assert MIN_SCAN_INTERVAL_MINUTES <= minutes <= MAX_SCAN_INTERVAL_MINUTES
    # Only meaningful once the floor is not what is binding.
    if minutes > MIN_SCAN_INTERVAL_MINUTES:
        assert estimated_daily_requests(requests_per_poll, minutes) <= (
            DAILY_REQUEST_BUDGET
        )


def test_recommended_interval_grows_with_the_fleet() -> None:
    """More vehicles mean a longer minimum interval."""
    one_car = recommended_scan_interval_minutes(15)
    ten_cars = recommended_scan_interval_minutes(150)
    assert ten_cars > one_car


def test_recommended_interval_handles_no_domains() -> None:
    """A zero request cost falls back to the default rather than dividing by it."""
    assert recommended_scan_interval_minutes(0) > 0
    assert recommended_scan_interval_minutes(-1) > 0


def test_daily_estimate_includes_token_refreshes() -> None:
    """The estimate accounts for more than just the polls themselves."""
    # 96 polls a day at 15 domains, plus hourly token refreshes.
    assert estimated_daily_requests(15, 15) == 96 * 15 + 24
    assert estimated_daily_requests(15, 0) == DAILY_REQUEST_BUDGET


def test_single_vehicle_gets_the_short_name() -> None:
    """One car needs no disambiguation, so entity IDs stay short."""
    assert build_device_names(["YV1CZ0000000123456"]) == {
        "YV1CZ0000000123456": "Polestar"
    }


def test_several_vehicles_are_distinguished_by_vin_serial() -> None:
    """Two cars are told apart by the serial part of their VINs."""
    names = build_device_names(["YV1CZ0000000123456", "YV1CZ0000000654321"])
    assert names == {
        "YV1CZ0000000123456": "Polestar 123456",
        "YV1CZ0000000654321": "Polestar 654321",
    }


def test_vins_sharing_a_serial_still_get_distinct_names() -> None:
    """A longer suffix is used when the usual six characters collide.

    The spec's own example VINs differ only in their first five characters,
    so this is not a hypothetical.
    """
    names = build_device_names(["YV1CZ0000000000000", "LPSVS0000000000000"])
    assert len(set(names.values())) == 2
    assert all(name.startswith("Polestar ") for name in names.values())


def test_device_names_handle_empty_and_duplicate_input() -> None:
    """A missing or repeated VIN must not raise or produce a clashing name."""
    assert build_device_names([]) == {}
    assert build_device_names(["VIN1", "VIN1"]) == {"VIN1": "Polestar"}
