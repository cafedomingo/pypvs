"""Model for an Enphase microinverter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from ..api import Match
from .varserver_coerce import float_var, report_time_var, str_var


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
            serial_number=str_var(data, "sn"),
            model=str_var(data, "prodMdlNm"),
            last_report_date=report_time_var(data),
            last_report_kw=float_var(data, "p3phsumKw"),
            last_report_voltage_v=float_var(data, "vln3phavgV"),
            last_report_current_a=float_var(data, "i3phsumA"),
            last_report_frequency_hz=float_var(data, "freqHz"),
            last_report_temperature_c=float_var(data, "tHtsnkDegc"),
            lte_kwh=float_var(data, "ltea3phsumKwh"),
            last_mppt_voltage_v=float_var(data, "vMppt1V"),
            last_mppt_current_a=float_var(data, "iMppt1A"),
            last_mppt_power_kw=float_var(data, "pMppt1Kw"),
        )
