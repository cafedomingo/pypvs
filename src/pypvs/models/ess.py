"""Model for an Equinox ESS (Energy Storage System)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from ..api import Match
from .values import get_float, get_report_time, get_str


def _percent(ratio: float | None) -> float | None:
    return None if ratio is None else ratio * 100.0


@dataclass(slots=True)
class PVSESS:
    """Model for an Equinox ESS (Energy Storage System)."""

    MATCH: ClassVar[str] = Match.ESS

    serial_number: str
    model: str
    last_report_date: int
    power_3ph_kw: float | None
    neg_lte_kwh: float | None
    pos_lte_kwh: float | None
    v1n_v: float | None
    v2n_v: float | None
    op_mode: str = ""
    soc_val: float | None = None
    customer_soc_val: float | None = None
    soh_val: float | None = None
    t_invtr_degc: float | None = None
    v_batt_v: float | None = None
    chrg_limit_pmax_kw: float | None = None
    dischrg_lim_pmax_kw: float | None = None
    max_t_batt_cell_degc: float | None = None
    min_t_batt_cell_degc: float | None = None
    max_v_batt_cell_v: float | None = None
    min_v_batt_cell_v: float | None = None

    @classmethod
    def from_varserver(cls, data: dict[str, Any]) -> PVSESS:
        """Initialize from one device's variables, as group_device_vars packs them."""
        soc_val_scaled = _percent(get_float(data, "socVal"))
        customer_soc_val_scaled = _percent(get_float(data, "customerSocVal"))
        soh_val_scaled = _percent(get_float(data, "sohVal"))

        return cls(
            serial_number=get_str(data, "sn"),
            model=get_str(data, "prodMdlNm"),
            last_report_date=get_report_time(data),
            power_3ph_kw=get_float(data, "p3phsumKw"),
            neg_lte_kwh=get_float(data, "negLtea3phsumKwh"),
            pos_lte_kwh=get_float(data, "posLtea3phsumKwh"),
            v1n_v=get_float(data, "v1nV"),
            v2n_v=get_float(data, "v2nV"),
            op_mode=get_str(data, "opMode"),
            soc_val=soc_val_scaled,
            customer_soc_val=customer_soc_val_scaled,
            soh_val=soh_val_scaled,
            t_invtr_degc=get_float(data, "tInvtrDegc"),
            v_batt_v=get_float(data, "vBattV"),
            chrg_limit_pmax_kw=get_float(data, "chrgLimitPmaxKw"),
            dischrg_lim_pmax_kw=get_float(data, "dischrgLimPmaxKw"),
            max_t_batt_cell_degc=get_float(data, "maxTBattCellDegc"),
            min_t_batt_cell_degc=get_float(data, "minTBattCellDegc"),
            max_v_batt_cell_v=get_float(data, "maxVBattCellV"),
            min_v_batt_cell_v=get_float(data, "minVBattCellV"),
        )
