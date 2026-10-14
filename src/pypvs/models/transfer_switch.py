"""Model for a MIDC (Microgrid Interconnected Device Controller)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from ..api import Match
from .varserver_coerce import float_var, report_time_var, str_var


@dataclass(slots=True)
class PVSTransferSwitch:
    """Model for a MIDC (Microgrid Interconnected Device Controller)."""

    MATCH: ClassVar[str] = Match.TRANSFER_SWITCH

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
        return cls(
            serial_number=str_var(data, "sn"),
            model=str_var(data, "prodMdlNm"),
            last_report_date=report_time_var(data),
            mid_state=str_var(data, "midStEnum"),
            pvd1_state=str_var(data, "pvd1StEnum"),
            temperature_c=float_var(data, "tDegc"),
            v1n_grid_v=float_var(data, "v1nGridV"),
            v1n_v=float_var(data, "v1nV"),
            v2n_grid_v=float_var(data, "v2nGridV"),
            v2n_v=float_var(data, "v2nV"),
            v_supply_v=float_var(data, "vSpplyV"),
        )
