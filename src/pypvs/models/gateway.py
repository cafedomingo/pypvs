"""Model for the PVS itself as a gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..api import INTERFACES_BY_MODEL, PVS6_ONLY_VARIABLES, Model, Variable, net_state
from .values import get_count, get_flag, get_float, get_int, get_str, get_text

#: read every poll; all required
CORE_VARS = (
    Variable.CPU_USAGE,
    Variable.FLASH_USAGE,
    Variable.HWREV,
    Variable.LMAC,
    Variable.MODEL,
    Variable.RAM_USAGE,
    Variable.SW_REV,
    Variable.SYS_TYPE,
    Variable.UPTIME,
)

#: read every few minutes with the interface states, all optional
EXTRA_VARS = (
    Variable.ESS_RESERVE_SOC,
    Variable.ESS_CONTROL_MODE,
    Variable.ACTIVE_INTERFACE,
    Variable.BOARDTYPE,
    Variable.FWREV,
    Variable.FLASHWEAR,
    Variable.USB_ERASE_COUNT,
    Variable.BROADBAND_CONNECTED,
    Variable.CELL_CONNECTED,
    Variable.LOW_DATA_MODE,
)
ESS_CONFIG_VARS = frozenset({Variable.ESS_RESERVE_SOC, Variable.ESS_CONTROL_MODE})


def _interfaces(model: str) -> tuple[str, ...]:
    return INTERFACES_BY_MODEL[
        Model.PVS5 if model.strip() == Model.PVS5 else Model.PVS6
    ]


def extra_vars(model: str, has_ess: bool) -> tuple[str, ...]:
    """The optional variables a PVS model has, with or without an ESS."""
    skip: set[str] = set()
    if model.strip() == Model.PVS5:
        skip |= PVS6_ONLY_VARIABLES
    if not has_ess:
        skip |= ESS_CONFIG_VARS
    return tuple(n for n in EXTRA_VARS if n not in skip) + tuple(
        net_state(name) for name in _interfaces(model)
    )


@dataclass(slots=True)
class PVSGateway:
    """Model for the PVS itself as a gateway."""

    model: str
    pvs_type: str
    hardware_version: str
    software_version: str
    uptime_s: float | None
    mac: str
    ram_usage_percent: int | None
    flash_usage_percent: int | None
    cpu_usage_percent: int | None
    flashwear_type_b_percent: int | None
    # Fields below are optional: older firmware or other PVS models may not
    # report them, and they default to None.
    firmware_revision: str | None = None
    board_type: str | None = None
    usb_erase_count: int | None = None
    active_interface: str | None = None
    #: link state per interface as the PVS reports it ("online", "ready",
    #: "N/A", ...); interface names differ between PVS5 and PVS6
    interface_states: dict[str, str] = field(default_factory=dict)
    broadband_connected: bool | None = None
    cell_connected: bool | None = None
    low_data_mode: int | None = None
    #: battery backup reserve as a 0-1 ratio of customer state of charge
    ess_reserve_soc: float | None = None
    ess_control_mode: str | None = None

    @classmethod
    def from_varserver(cls, data: dict[str, Any]) -> PVSGateway:
        """Initialize from /sys/info and the extra varserver variables."""
        pvs_model = get_str(data, Variable.MODEL)
        hw_rev = get_str(data, Variable.HWREV)

        # tenths in hex, e.g. "0x02" is 20%; only on the PVS6
        flashwear = get_count(data, Variable.FLASHWEAR)
        flashwear_percent = None if flashwear is None else min(flashwear * 10, 100)

        return cls(
            model=get_str(data, Variable.SYS_TYPE),
            pvs_type=pvs_model,
            hardware_version=f"{pvs_model} {hw_rev}",
            software_version=get_str(data, Variable.SW_REV),
            uptime_s=get_float(data, Variable.UPTIME),
            mac=get_str(data, Variable.LMAC),
            ram_usage_percent=get_int(data, Variable.RAM_USAGE),
            flash_usage_percent=get_int(data, Variable.FLASH_USAGE),
            cpu_usage_percent=get_int(data, Variable.CPU_USAGE),
            flashwear_type_b_percent=flashwear_percent,
            firmware_revision=get_text(data, Variable.FWREV),
            board_type=get_text(data, Variable.BOARDTYPE),
            usb_erase_count=get_count(data, Variable.USB_ERASE_COUNT),
            active_interface=get_text(data, Variable.ACTIVE_INTERFACE),
            interface_states={
                name: state
                for name in _interfaces(pvs_model)
                if (state := get_text(data, net_state(name))) is not None
            },
            broadband_connected=get_flag(data, Variable.BROADBAND_CONNECTED),
            cell_connected=get_flag(data, Variable.CELL_CONNECTED),
            low_data_mode=get_int(data, Variable.LOW_DATA_MODE),
            ess_reserve_soc=get_float(data, Variable.ESS_RESERVE_SOC),
            ess_control_mode=get_text(data, Variable.ESS_CONTROL_MODE),
        )
