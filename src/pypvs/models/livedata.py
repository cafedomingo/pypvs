"""Model for PVS live data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..api import Variable
from .values import get_float, get_text, get_unix_time

#: attribute -> its /sys/livedata variable and the function that reads it
LIVEDATA_FIELDS: dict[str, tuple[Variable, Callable[[dict[str, Any], str], Any]]] = {
    "time": (Variable.LIVEDATA_TIME, get_unix_time),
    "pv_p": (Variable.LIVEDATA_PV_P, get_float),
    "pv_en": (Variable.LIVEDATA_PV_EN, get_float),
    "net_p": (Variable.LIVEDATA_NET_P, get_float),
    "net_en": (Variable.LIVEDATA_NET_EN, get_float),
    "site_load_p": (Variable.LIVEDATA_SITE_LOAD_P, get_float),
    "site_load_en": (Variable.LIVEDATA_SITE_LOAD_EN, get_float),
    "ess_en": (Variable.LIVEDATA_ESS_EN, get_float),
    "ess_p": (Variable.LIVEDATA_ESS_P, get_float),
    "soc": (Variable.LIVEDATA_SOC, get_float),
    "backup_time_remaining": (Variable.LIVEDATA_BACKUP_TIME_REMAINING, get_float),
    "midstate": (Variable.LIVEDATA_MIDSTATE, get_text),
}

_VAR_PATH_TO_ATTR: dict[str, str] = {
    var_path: attr for attr, (var_path, _) in LIVEDATA_FIELDS.items()
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
                attr: get(data, var_path)
                for attr, (var_path, get) in LIVEDATA_FIELDS.items()
            }
        )
