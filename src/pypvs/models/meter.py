"""Model for a built-in PVS meter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .varserver_coerce import float_var, str_var


@dataclass(slots=True)
class PVSMeter:
    """Model for a built-in PVS meter."""

    serial_number: str
    model: str
    last_report_date: int
    power_3ph_kw: float
    voltage_3ph_v: float
    current_3ph_a: float
    freq_hz: float
    lte_3ph_kwh: float
    ct_scale_factor: float
    i1_a: float
    i2_a: float
    neg_lte_kwh: float
    net_lte_kwh: float
    p1_kw: float
    p2_kw: float
    pos_lte_kwh: float
    q3phsum_kvar: float
    s3phsum_kva: float
    tot_pf_ratio: float
    v12_v: float
    v1n_v: float
    v2n_v: float

    @classmethod
    def from_varserver(cls, data: dict[str, Any]) -> PVSMeter:
        """Initialize from /sys/devices/meter/*/* varserver variables packed in JSON."""

        # Convert date from format "2024-09-30T16:15:00Z" to UTC seconds
        date_str = str_var(data, "msmtEps", "1970-01-01T00:00:00Z")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            last_report_date = int(dt.timestamp())
        except Exception:
            last_report_date = 0

        return cls(
            serial_number=str_var(data, "sn"),
            model=str_var(data, "prodMdlNm"),
            last_report_date=last_report_date,
            power_3ph_kw=float_var(data, "p3phsumKw"),
            voltage_3ph_v=float_var(data, "vln3phavgV"),
            current_3ph_a=float_var(data, "i3phsumA"),
            freq_hz=float_var(data, "freqHz"),
            lte_3ph_kwh=float_var(data, "ltea3phsumKwh"),
            ct_scale_factor=float_var(data, "ctSclFctr", 1.0),
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
