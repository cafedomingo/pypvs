"""Model for PVS live data."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..api import Variable

# Canonical field definitions for livedata.
# Each tuple: (ws_field_name, var_path, attr_name, value_type)
LIVEDATA_FIELD_DEFINITIONS: tuple[tuple[str, str, str, str], ...] = (
    ("time", Variable.LIVEDATA_TIME, "time", "timestamp"),
    ("pv_p", Variable.LIVEDATA_PV_P, "pv_p", "numeric"),
    ("pv_en", Variable.LIVEDATA_PV_EN, "pv_en", "numeric"),
    ("net_p", Variable.LIVEDATA_NET_P, "net_p", "numeric"),
    ("net_en", Variable.LIVEDATA_NET_EN, "net_en", "numeric"),
    ("site_load_p", Variable.LIVEDATA_SITE_LOAD_P, "site_load_p", "numeric"),
    ("site_load_en", Variable.LIVEDATA_SITE_LOAD_EN, "site_load_en", "numeric"),
    ("ess_en", Variable.LIVEDATA_ESS_EN, "ess_en", "numeric"),
    ("ess_p", Variable.LIVEDATA_ESS_P, "ess_p", "numeric"),
    ("soc", Variable.LIVEDATA_SOC, "soc", "numeric"),
    (
        "backupTimeRemaining",
        Variable.LIVEDATA_BACKUP_TIME_REMAINING,
        "backup_time_remaining",
        "numeric",
    ),
    ("midstate", Variable.LIVEDATA_MIDSTATE, "midstate", "string"),
)

# Mapping from varserver path to attribute name (derived from field definitions)
_VAR_PATH_TO_ATTR: dict[str, str] = {
    var_path: attr_name for _, var_path, attr_name, _ in LIVEDATA_FIELD_DEFINITIONS
}


@dataclass(slots=True)
class PVSLiveData:
    """Container for PVS live data values.

    Attributes:
        time: Timestamp of the live data reading
        pv_p: Solar production power in kW
        pv_en: Solar production energy in kWh
        net_p: Net grid power in kW (positive = importing, negative = exporting)
        net_en: Net grid energy in kWh
        site_load_p: Site load power in kW
        site_load_en: Site load energy in kWh
        ess_en: Battery energy in kWh
        ess_p: Battery power in kW (positive = discharging, negative = charging)
        soc: Battery state of charge as a 0-1 ratio
        backup_time_remaining: Estimated backup time remaining in minutes
        midstate: MIDC transfer switch state
    """

    time: datetime | None = None
    pv_p: float | None = None
    pv_en: float | None = None
    net_p: float | None = None
    net_en: float | None = None
    site_load_p: float | None = None
    site_load_en: float | None = None
    ess_en: float | None = None
    ess_p: float | None = None
    soc: float | None = None
    backup_time_remaining: float | None = None
    midstate: str | None = None

    def get(self, var_name: str) -> Any:
        """Get value by varserver path.

        Args:
            var_name: The varserver path (e.g., "/sys/livedata/pv_p")

        Returns:
            The value for that path, or None if not found
        """
        attr = _VAR_PATH_TO_ATTR.get(var_name)
        if attr:
            return getattr(self, attr, None)
        return None

    @classmethod
    def from_varserver(cls, data: dict[str, Any]) -> PVSLiveData:
        """Initialize from /sys/livedata/* varserver variables.

        Args:
            data: Dictionary with varserver paths as keys

        Returns:
            PVSLiveData instance with parsed values
        """
        return cls(
            **{
                attr: getattr(cls, f"_parse_{value_type}")(data.get(var_path))
                for _, var_path, attr, value_type in LIVEDATA_FIELD_DEFINITIONS
            }
        )

    @staticmethod
    def _parse_numeric(value: Any) -> float | None:
        """Parse a numeric value from varserver response."""
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            try:
                number = float(value)
            except OverflowError:  # an int too large for a float
                return None
        elif isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                return None
        else:
            return None
        # nan/inf are "no reading"; NaN would also never compare equal
        return number if math.isfinite(number) else None

    @staticmethod
    def _parse_string(value: Any) -> str | None:
        """Parse a string value; the wire may carry it as a number."""
        return None if value is None else str(value)

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        """Parse a timestamp value from varserver response.

        Handles both Unix seconds and milliseconds formats.
        """
        if value is None:
            return None
        try:
            timestamp: float = int(value)
            current_time = datetime.now(UTC).timestamp()

            # Detect milliseconds vs seconds
            if timestamp > current_time + (365 * 24 * 3600):
                timestamp = timestamp / 1000

            # Validate
            if timestamp < 0 or timestamp > current_time + (365 * 24 * 3600):
                return None

            return datetime.fromtimestamp(timestamp, tz=UTC)
        except (ValueError, TypeError, OSError, OverflowError):
            return None
