"""Model for an Equinox ESS (Energy Storage System)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from ..api import Match
from .varserver_coerce import float_var, report_time_var, str_var


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
        soc_val_scaled = _percent(float_var(data, "socVal"))
        customer_soc_val_scaled = _percent(float_var(data, "customerSocVal"))
        soh_val_scaled = _percent(float_var(data, "sohVal"))

        return cls(
            serial_number=str_var(data, "sn"),
            model=str_var(data, "prodMdlNm"),
            last_report_date=report_time_var(data),
            power_3ph_kw=float_var(data, "p3phsumKw"),
            neg_lte_kwh=float_var(data, "negLtea3phsumKwh"),
            pos_lte_kwh=float_var(data, "posLtea3phsumKwh"),
            v1n_v=float_var(data, "v1nV"),
            v2n_v=float_var(data, "v2nV"),
            op_mode=str_var(data, "opMode"),
            soc_val=soc_val_scaled,
            customer_soc_val=customer_soc_val_scaled,
            soh_val=soh_val_scaled,
            t_invtr_degc=float_var(data, "tInvtrDegc"),
            v_batt_v=float_var(data, "vBattV"),
            chrg_limit_pmax_kw=float_var(data, "chrgLimitPmaxKw"),
            dischrg_lim_pmax_kw=float_var(data, "dischrgLimPmaxKw"),
            max_t_batt_cell_degc=float_var(data, "maxTBattCellDegc"),
            min_t_batt_cell_degc=float_var(data, "minTBattCellDegc"),
            max_v_batt_cell_v=float_var(data, "maxVBattCellV"),
            min_v_batt_cell_v=float_var(data, "minVBattCellV"),
        )
