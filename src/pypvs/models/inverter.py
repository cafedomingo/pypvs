"""Model for an Enphase microinverter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .varserver_coerce import float_var, report_time_var, str_var


@dataclass(slots=True)
class PVSInverter:
    """
    Model for an Enphase microinverter.

    Attributes:
        serial_number (str): The serial number of the inverter.
        model (str): The model name or number of the inverter.
        last_report_date (Optional[int]): The timestamp of the
            last report in UTC seconds.
        last_report_kw (Optional[float|str]): The last reported AC power
            output in kilowatts.
        last_report_voltage_v (Optional[float|str]): The last reported AC
            voltage in volts.
        last_report_current_a (Optional[float|str]): The last reported AC
            current in amperes.
        last_report_frequency_hz (Optional[float|str]): The last reported AC
            frequency in hertz.
        last_report_temperature_c (Optional[float|str]): The last reported
            temperature in degrees Celsius.
        lte_kwh (Optional[float|str]): The lifetime energy produced by the
            inverter in kilowatt-hours.
        last_mppt_voltage_v (Optional[float|str]): The DC voltage from the panel.
        last_mppt_current_a (Optional[float|str]): The DC current from the panel.
        last_mppt_power_kw (Optional[float|str]): The DC power from the panel.

    Methods:
        from_varserver(data: dict[str, Any]) -> PVSInverter:
            Class method to initialize a PVSInverter instance from a
            dictionary of varserver variables.
            Converts the date string in ISO 8601 format to a UTC timestamp.
    """

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
        """Initialize from /sys/devices/inverter/*/* varserver variables
        packed in JSON to a PVSInverter instance."""

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
