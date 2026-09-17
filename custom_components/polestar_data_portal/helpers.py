"""Value helpers shared by the Polestar Data Portal entity platforms.

The API returns protobuf-flavoured JSON: enums are fully qualified upper-case
strings, timestamps are ``{seconds, nanos}`` objects with ``seconds`` encoded
as a *string*, and a few numeric fields (altitude, speed) are strings too.
These helpers normalise all of that into the plain Python types Home Assistant
expects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from typing import Any

UNSPECIFIED_SUFFIXES = ("UNSPECIFIED", "UNDEFINED", "UNKNOWN")


@dataclass(frozen=True)
class EnumSpec:
    """Maps one API enum onto a Home Assistant enum sensor.

    ``prefix`` is the shared protobuf prefix stripped from every value so
    ``CHARGING_STATUS_V2_CHARGING`` is reported as ``charging``.
    """

    prefix: str
    values: tuple[str, ...]

    @property
    def options(self) -> list[str]:
        """Return the Home Assistant ``options`` list for this enum.

        Placeholder members are left out: they carry no information and an
        "unspecified" state is better represented as unknown.
        """
        return [
            option
            for value in self.values
            if (option := self._normalize(value)) is not None
        ]

    def _normalize(self, raw: Any) -> str | None:
        """Strip the protobuf prefix and lowercase, without validating."""
        if not isinstance(raw, str) or not raw:
            return None
        if raw.endswith(UNSPECIFIED_SUFFIXES):
            return None
        return raw.removeprefix(self.prefix).lower() or None

    def to_option(self, raw: Any) -> str | None:
        """Convert a raw API enum value to its Home Assistant option.

        A value that is not part of the published enum returns None. Home
        Assistant rejects an enum state outside the declared options, so a
        member Polestar adds after this spec was captured has to surface as
        unknown rather than break the sensor.
        """
        option = self._normalize(raw)
        if option is None or option not in _option_set(self.prefix, self.values):
            return None
        return option

    def is_set(self, raw: Any) -> bool:
        """Return True when the value is a real, non-placeholder member."""
        return self.to_option(raw) is not None


@cache
def _option_set(prefix: str, values: tuple[str, ...]) -> frozenset[str]:
    """Cache the valid option set for one enum."""
    return frozenset(EnumSpec(prefix=prefix, values=values).options)


def nested(data: Any, *keys: str) -> Any:
    """Return a nested value, or None when any level is missing."""
    for key in keys:
        if not isinstance(data, Mapping):
            return None
        data = data.get(key)
    return data


def to_float(value: Any) -> float | None:
    """Parse a number that the API may encode as a string."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # The API uses NaN/inf for "no reading"; Home Assistant cannot store them.
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def to_int(value: Any) -> int | None:
    """Parse an integer that the API may encode as a string or float."""
    result = to_float(value)
    return None if result is None else int(result)


def timestamp_to_datetime(value: Any) -> datetime | None:
    """Convert a ``TelemetryTimestamp`` object to an aware datetime.

    ``seconds`` is documented as a string; a zero or missing value means the
    event never happened rather than 1970-01-01.
    """
    if not isinstance(value, Mapping):
        return None

    seconds = to_int(value.get("seconds"))
    if not seconds:
        return None

    nanos = to_int(value.get("nanos")) or 0
    return datetime.fromtimestamp(seconds + nanos / 1_000_000_000, tz=UTC)


def iso_to_datetime(value: Any) -> datetime | None:
    """Parse an ISO 8601 string such as ``metaReceivedAt`` or ``updatedAt``."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def daily_time_to_string(value: Any) -> str | None:
    """Format a ``DailyTime`` object as ``HH:MM``."""
    if not isinstance(value, Mapping):
        return None
    hour = to_int(value.get("hour"))
    minute = to_int(value.get("minute"))
    if hour is None or minute is None:
        return None
    return f"{hour:02d}:{minute:02d}"
