"""Model for the PVS itself as a gateway."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .varserver_coerce import float_var, int_var, str_var

VAR_FWREV = "/sys/info/fwrev"
VAR_BOARDTYPE = "/sys/info/boardtype"
VAR_ACTIVE_INTERFACE = "/sys/info/active_interface"
VAR_USB_ERASE_COUNT = "/sys/pvs/usb_erase_count"
VAR_BROADBAND_CONNECTED = "/sys/toggle_cell/broadband_connected"
VAR_CELL_CONNECTED = "/sys/toggle_cell/cell_connected"
VAR_LOW_DATA_MODE = "/sys/toggle_cell/low_data_mode"
ESS_RESERVE_SOC = "/ess/config/dcm/control_param/min_customer_soc"
ESS_CONTROL_MODE = "/ess/config/dcm/mode_param/control_mode"
VAR_FLASHWEAR = "/sys/pvs/flashwear_type_b"

#: read on every poll; only flashwear may be missing (PVS6-only)
CORE_VARS = (
    "/sys/info/sys_type",
    "/sys/info/model",
    "/sys/info/hwrev",
    "/sys/info/sw_rev",
    "/sys/info/uptime",
    "/sys/info/lmac",
    "/sys/info/ram_usage",
    "/sys/info/flash_usage",
    "/sys/info/cpu_usage",
    VAR_FLASHWEAR,
)
OPTIONAL_CORE_VARS = frozenset({VAR_FLASHWEAR})
#: documented interfaces: PVS6 (wan0, wan1, sta0, wwan0), PVS5 (wan, cell, plc)
INTERFACES = ("wan0", "wan1", "sta0", "wwan0", "wan", "cell", "plc")
#: read every few minutes, all optional; a PVS answers 400 for names it lacks
EXTRA_VARS = (
    VAR_FWREV,
    VAR_BOARDTYPE,
    VAR_ACTIVE_INTERFACE,
    VAR_USB_ERASE_COUNT,
    VAR_BROADBAND_CONNECTED,
    VAR_CELL_CONNECTED,
    VAR_LOW_DATA_MODE,
    ESS_RESERVE_SOC,
    ESS_CONTROL_MODE,
    *(f"/net/{name}/state" for name in INTERFACES),
)
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
        """Initialize from a /sys/info varserver variables"""

        pvs_model = str_var(data, "/sys/info/model").strip()
        hw_rev = str_var(data, "/sys/info/hwrev").strip()

        # flashwear_type_b is reported as a hex string (e.g. "0x02")
        # The decimal value is multiplied by 10 to get a percentage.
        # Only available on PVS6; returns None when absent.
        raw_flashwear = str_var(data, VAR_FLASHWEAR, None)
        flashwear: int | None = None
        if raw_flashwear is not None:
            try:
                flashwear = min(int(raw_flashwear, 16) * 10, 100)
            except (ValueError, TypeError):
                flashwear = None

        return cls(
            model=str_var(data, "/sys/info/sys_type").strip(),
            pvs_type=pvs_model,
            hardware_version=f"{pvs_model} {hw_rev}",
            software_version=str_var(data, "/sys/info/sw_rev"),
            uptime_s=float_var(data, "/sys/info/uptime"),
            mac=str_var(data, "/sys/info/lmac"),
            ram_usage_percent=int_var(data, "/sys/info/ram_usage"),
            flash_usage_percent=int_var(data, "/sys/info/flash_usage"),
            cpu_usage_percent=int_var(data, "/sys/info/cpu_usage"),
            flashwear_type_b_percent=flashwear,
            firmware_revision=_text(data, VAR_FWREV),
            board_type=_text(data, VAR_BOARDTYPE),
            usb_erase_count=_count(data, VAR_USB_ERASE_COUNT),
            active_interface=_text(data, VAR_ACTIVE_INTERFACE),
            interface_states={
                name: state
                for name in INTERFACES
                if (state := _text(data, f"/net/{name}/state")) is not None
            },
            broadband_connected=_flag(data, VAR_BROADBAND_CONNECTED),
            cell_connected=_flag(data, VAR_CELL_CONNECTED),
            low_data_mode=_whole(data, VAR_LOW_DATA_MODE),
            ess_reserve_soc=float_var(data, ESS_RESERVE_SOC),
            ess_control_mode=_text(data, ESS_CONTROL_MODE),
        )
