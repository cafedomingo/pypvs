"""Model for a built-in PVS meter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from ..api import Match
from .values import get_float, get_report_time, get_str


@dataclass(slots=True)
class PVSMeter:
    """Model for a built-in PVS meter."""

    MATCH: ClassVar[str] = Match.METERS

    serial_number: str
    model: str
    last_report_date: int
    power_3ph_kw: float | None
    voltage_3ph_v: float | None
    current_3ph_a: float | None
    freq_hz: float | None
    lte_3ph_kwh: float | None
    ct_scale_factor: float | None
    i1_a: float | None
    i2_a: float | None
    neg_lte_kwh: float | None
    net_lte_kwh: float | None
    p1_kw: float | None
    p2_kw: float | None
    pos_lte_kwh: float | None
    q3phsum_kvar: float | None
    s3phsum_kva: float | None
    tot_pf_ratio: float | None
    v12_v: float | None
    v1n_v: float | None
    v2n_v: float | None

    @classmethod
    def from_varserver(cls, data: dict[str, Any]) -> PVSMeter:
        """Initialize from one device's variables, as group_device_vars packs them."""
        return cls(
            serial_number=get_str(data, "sn"),
            model=get_str(data, "prodMdlNm"),
            last_report_date=get_report_time(data),
            power_3ph_kw=get_float(data, "p3phsumKw"),
            voltage_3ph_v=get_float(data, "vln3phavgV"),
            current_3ph_a=get_float(data, "i3phsumA"),
            freq_hz=get_float(data, "freqHz"),
            lte_3ph_kwh=get_float(data, "ltea3phsumKwh"),
            ct_scale_factor=get_float(data, "ctSclFctr"),
            i1_a=get_float(data, "i1A"),
            i2_a=get_float(data, "i2A"),
            neg_lte_kwh=get_float(data, "negLtea3phsumKwh"),
            net_lte_kwh=get_float(data, "netLtea3phsumKwh"),
            p1_kw=get_float(data, "p1Kw"),
            p2_kw=get_float(data, "p2Kw"),
            pos_lte_kwh=get_float(data, "posLtea3phsumKwh"),
            q3phsum_kvar=get_float(data, "q3phsumKvar"),
            s3phsum_kva=get_float(data, "s3phsumKva"),
            tot_pf_ratio=get_float(data, "totPfRto"),
            v12_v=get_float(data, "v12V"),
            v1n_v=get_float(data, "v1nV"),
            v2n_v=get_float(data, "v2nV"),
        )
