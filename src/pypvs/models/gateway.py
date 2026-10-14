"""Model for the PVS itself as a gateway."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..api import INTERFACES_BY_MODEL, PVS6_ONLY_VARIABLES, Model, Variable, net_state
from .varserver_coerce import float_var, int_var, str_var

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


# "TBD" is varserver's default for a string variable nothing has set
_PLACEHOLDERS = {"", "TBD"}


def _text(data: dict[str, Any], key: str) -> str | None:
    value = str_var(data, key, None)
    if value is None:
        return None
    value = value.strip()
    return None if value in _PLACEHOLDERS else value


def _flag(data: dict[str, Any], key: str) -> bool | None:
    value = float_var(data, key)
    return None if value is None else value != 0


def _whole(data: dict[str, Any], key: str) -> int | None:
    value = float_var(data, key)
    return None if value is None or not value.is_integer() else int(value)


def _count(data: dict[str, Any], key: str) -> int | None:
    """An unsigned counter, decimal or 0x-prefixed hex."""
    value = _text(data, key)
    if value is None:
        return None
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", value):
        return int(value, 16)
    return int(value) if re.fullmatch(r"[0-9]+", value) else None


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
        pvs_model = str_var(data, Variable.MODEL).strip()
        hw_rev = str_var(data, Variable.HWREV).strip()

        # flashwear_type_b is reported as a hex string (e.g. "0x02")
        # The decimal value is multiplied by 10 to get a percentage.
        # Only available on PVS6; returns None when absent.
        raw_flashwear = str_var(data, Variable.FLASHWEAR, None)
        flashwear: int | None = None
        if raw_flashwear is not None:
            try:
                flashwear = min(int(raw_flashwear, 16) * 10, 100)
            except (ValueError, TypeError):
                flashwear = None

        return cls(
            model=str_var(data, Variable.SYS_TYPE).strip(),
            pvs_type=pvs_model,
            hardware_version=f"{pvs_model} {hw_rev}",
            software_version=str_var(data, Variable.SW_REV),
            uptime_s=float_var(data, Variable.UPTIME),
            mac=str_var(data, Variable.LMAC),
            ram_usage_percent=int_var(data, Variable.RAM_USAGE),
            flash_usage_percent=int_var(data, Variable.FLASH_USAGE),
            cpu_usage_percent=int_var(data, Variable.CPU_USAGE),
            flashwear_type_b_percent=flashwear,
            firmware_revision=_text(data, Variable.FWREV),
            board_type=_text(data, Variable.BOARDTYPE),
            usb_erase_count=_count(data, Variable.USB_ERASE_COUNT),
            active_interface=_text(data, Variable.ACTIVE_INTERFACE),
            interface_states={
                name: state
                for name in _interfaces(pvs_model)
                if (state := _text(data, net_state(name))) is not None
            },
            broadband_connected=_flag(data, Variable.BROADBAND_CONNECTED),
            cell_connected=_flag(data, Variable.CELL_CONNECTED),
            low_data_mode=_whole(data, Variable.LOW_DATA_MODE),
            ess_reserve_soc=float_var(data, Variable.ESS_RESERVE_SOC),
            ess_control_mode=_text(data, Variable.ESS_CONTROL_MODE),
        )
