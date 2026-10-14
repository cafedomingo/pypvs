"""Model for a MIDC (Microgrid Interconnected Device Controller)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from ..api import Match
from .values import get_float, get_report_time, get_str


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
        """Initialize from one device's variables, as group_device_vars packs them."""
        return cls(
            serial_number=get_str(data, "sn"),
            model=get_str(data, "prodMdlNm"),
            last_report_date=get_report_time(data),
            mid_state=get_str(data, "midStEnum"),
            pvd1_state=get_str(data, "pvd1StEnum"),
            temperature_c=get_float(data, "tDegc"),
            v1n_grid_v=get_float(data, "v1nGridV"),
            v1n_v=get_float(data, "v1nV"),
            v2n_grid_v=get_float(data, "v2nGridV"),
            v2n_v=get_float(data, "v2nV"),
            v_supply_v=get_float(data, "vSpplyV"),
        )
