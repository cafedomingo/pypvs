"""Model for a built-in PVS meter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from ..api import Match
from .varserver_coerce import float_var, report_time_var, str_var


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
        """Initialize from /sys/devices/meter/*/* varserver variables packed in JSON."""

        return cls(
            serial_number=str_var(data, "sn"),
            model=str_var(data, "prodMdlNm"),
            last_report_date=report_time_var(data),
            power_3ph_kw=float_var(data, "p3phsumKw"),
            voltage_3ph_v=float_var(data, "vln3phavgV"),
            current_3ph_a=float_var(data, "i3phsumA"),
            freq_hz=float_var(data, "freqHz"),
            lte_3ph_kwh=float_var(data, "ltea3phsumKwh"),
            ct_scale_factor=float_var(data, "ctSclFctr"),
            i1_a=float_var(data, "i1A"),
            i2_a=float_var(data, "i2A"),
            neg_lte_kwh=float_var(data, "negLtea3phsumKwh"),
            net_lte_kwh=float_var(data, "netLtea3phsumKwh"),
            p1_kw=float_var(data, "p1Kw"),
            p2_kw=float_var(data, "p2Kw"),
            pos_lte_kwh=float_var(data, "posLtea3phsumKwh"),
            q3phsum_kvar=float_var(data, "q3phsumKvar"),
            s3phsum_kva=float_var(data, "s3phsumKva"),
            tot_pf_ratio=float_var(data, "totPfRto"),
            v12_v=float_var(data, "v12V"),
            v1n_v=float_var(data, "v1nV"),
            v2n_v=float_var(data, "v2nV"),
        )
