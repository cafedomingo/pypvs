"""Model for a MIDC (Microgrid Interconnected Device Controller)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .varserver_coerce import float_var, str_var


@dataclass(slots=True)
class PVSTransferSwitch:
    """Model for a MIDC (Microgrid Interconnected Device Controller)."""

    serial_number: str
    model: str
    last_report_date: int
    mid_state: str = ""
    pvd1_state: str = ""
    temperature_c: float | None = None
    v1n_grid_v: float | None = None
    v1n_v: float | None = None
    v2n_grid_v: float | None = None
    v2n_v: float | None = None
    v_supply_v: float | None = None

    @classmethod
    def from_varserver(cls, data: dict[str, Any]) -> PVSTransferSwitch:
        """
        Initialize from /sys/devices/transfer_switch/*/* varserver variables packed
        in JSON.
        """
        date_str = str_var(data, "msmtEps", "1970-01-01T00:00:00Z")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            last_report_date = int(dt.timestamp())
        except Exception:
            last_report_date = 0

        return cls(
            serial_number=str_var(data, "sn"),
            model=str_var(data, "prodMdlNm"),
            last_report_date=last_report_date,
            mid_state=str_var(data, "midStEnum"),
            pvd1_state=str_var(data, "pvd1StEnum"),
            temperature_c=float_var(data, "tDegc"),
            v1n_grid_v=float_var(data, "v1nGridV"),
            v1n_v=float_var(data, "v1nV"),
            v2n_grid_v=float_var(data, "v2nGridV"),
            v2n_v=float_var(data, "v2nV"),
            v_supply_v=float_var(data, "vSpplyV"),
        )
