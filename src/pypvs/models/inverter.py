"""Model for an Enphase microinverter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from ..api import Match
from .values import get_float, get_report_time, get_str


@dataclass(slots=True)
class PVSInverter:
    """Model for an Enphase microinverter.

    Values the inverter did not report are None.

    Attributes:
        serial_number: The serial number of the inverter.
        model: The model name or number of the inverter.
        last_report_date: When the inverter last reported, in UTC seconds; 0
            if unknown.
        last_report_kw: AC power in kilowatts.
        last_report_voltage_v: AC voltage in volts.
        last_report_current_a: AC current in amperes.
        last_report_frequency_hz: AC frequency in hertz.
        last_report_temperature_c: Heatsink temperature in degrees Celsius.
        lte_kwh: Lifetime energy produced in kilowatt-hours.
        last_mppt_voltage_v: DC voltage from the panel.
        last_mppt_current_a: DC current from the panel.
        last_mppt_power_kw: DC power from the panel, in kilowatts.
    """

    MATCH: ClassVar[str] = Match.INVERTERS

    serial_number: str
    model: str
    last_report_date: int | None = None
    last_report_kw: float | None = None
    last_report_voltage_v: float | None = None
    last_report_current_a: float | None = None
    last_report_frequency_hz: float | None = None
    last_report_temperature_c: float | None = None
    lte_kwh: float | None = None
    last_mppt_voltage_v: float | None = None
    last_mppt_current_a: float | None = None
    last_mppt_power_kw: float | None = None

    @classmethod
    def from_varserver(cls, data: dict[str, Any]) -> PVSInverter:
        """Initialize from one device's variables, as group_device_vars packs them."""
        return cls(
            serial_number=get_str(data, "sn"),
            model=get_str(data, "prodMdlNm"),
            last_report_date=get_report_time(data),
            last_report_kw=get_float(data, "p3phsumKw"),
            last_report_voltage_v=get_float(data, "vln3phavgV"),
            last_report_current_a=get_float(data, "i3phsumA"),
            last_report_frequency_hz=get_float(data, "freqHz"),
            last_report_temperature_c=get_float(data, "tHtsnkDegc"),
            lte_kwh=get_float(data, "ltea3phsumKwh"),
            last_mppt_voltage_v=get_float(data, "vMppt1V"),
            last_mppt_current_a=get_float(data, "iMppt1A"),
            last_mppt_power_kw=get_float(data, "pMppt1Kw"),
        )
