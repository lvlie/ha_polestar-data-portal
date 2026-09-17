"""Value helpers shared by the Polestar Data Portal entity platforms.

The API returns protobuf-flavoured JSON: enums are fully qualified upper-case
strings, timestamps are ``{seconds, nanos}`` objects with ``seconds`` encoded
as a *string*, and a few numeric fields (altitude, speed) are strings too.
These helpers normalise all of that into the plain Python types Home Assistant
expects.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from typing import Any

from .const import MANUFACTURER

UNSPECIFIED_SUFFIXES = ("UNSPECIFIED", "UNDEFINED", "UNKNOWN")

# How much of a VIN is used to tell two vehicles on one account apart. Six
# characters is the serial section, which differs between any two real cars.
VIN_SUFFIX_LENGTH = 6


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
    """Parse a timestamp string such as ``metaReceivedAt`` or ``updatedAt``.

    The spec types these as plain strings without a format, and the API uses
    two of them: ``metaReceivedAt`` is ISO 8601, while the ``updatedAt`` on
    charging settings is epoch milliseconds in a string, for example
    ``"1789558748374"``. Both are accepted here.
    """
    if not isinstance(value, str) or not (value := value.strip()):
        return None

    if value.lstrip("-").isdigit():
        epoch = int(value)
        # Milliseconds since the epoch are ~1e12 today, seconds ~1e9. Anything
        # at or above this threshold is far past any plausible date in seconds.
        if abs(epoch) >= 100_000_000_000:
            epoch /= 1000
        try:
            return datetime.fromtimestamp(epoch, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def daily_time_to_string(value: Any) -> str | None:
    """Format a ``DailyTime`` object as ``HH:MM``.

    The API leaves out the half of the time that is zero, so a timer set for
    08:00 arrives as ``{"hour": 8}`` with no ``minute``. A missing component
    therefore means zero, not unknown; only an object with neither is unusable.
    """
    if not isinstance(value, Mapping):
        return None
    hour = to_int(value.get("hour"))
    minute = to_int(value.get("minute"))
    if hour is None and minute is None:
        return None
    return f"{hour or 0:02d}:{minute or 0:02d}"


def build_device_names(vins: Sequence[str]) -> dict[str, str]:
    """Return the device name to use for each VIN on an account.

    A single vehicle is simply "Polestar", which keeps the entity IDs it
    generates short: ``sensor.polestar_battery``. Only when an account holds
    several vehicles is a VIN suffix added to tell them apart, using the
    shortest suffix that is unique across the account so two cars whose
    serials happen to end in the same digits still get distinct names.

    The caller passes every VIN on the account, not just the ones that set up
    successfully, so a vehicle temporarily missing a scope cannot make the
    other devices rename themselves.

    Only the serial section of the VIN is used, never the whole thing: the
    device name decides the entity IDs, and Home Assistant writes those to the
    log, to automation traces and to the recorder. The full VIN stays on the
    device as its serial number and in each entity's unique ID.
    """
    unique = list(dict.fromkeys(vins))
    if len(unique) <= 1:
        return dict.fromkeys(unique, MANUFACTURER)

    longest = max(len(vin) for vin in unique)
    for length in range(VIN_SUFFIX_LENGTH, longest + 1):
        suffixes = {vin: vin[-length:] for vin in unique}
        if len(set(suffixes.values())) == len(unique):
            return {vin: f"{MANUFACTURER} {suffix}" for vin, suffix in suffixes.items()}

    # Identical VINs cannot happen, but never return a name that hides one.
    return {vin: f"{MANUFACTURER} {vin}" for vin in unique}


def mask_vin(vin: str) -> str:
    """Return a VIN safe to write to a log file.

    A VIN identifies a specific car and its owner, and Home Assistant logs
    routinely get pasted into bug reports, so only the last four characters
    are kept.
    """
    if not isinstance(vin, str) or len(vin) <= 4:
        return "****"
    return f"****{vin[-4:]}"
