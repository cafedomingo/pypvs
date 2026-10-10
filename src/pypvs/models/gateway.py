"""Model for the PVS itself as a gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .varserver_coerce import float_var, int_var, str_var

INTERFACES = ("wan0", "wan1", "sta0", "wwan0")
ESS_RESERVE_SOC = "/ess/config/dcm/control_param/min_customer_soc"
ESS_CONTROL_MODE = "/ess/config/dcm/mode_param/control_mode"


def _flag(data: dict[str, Any], key: str) -> bool | None:
    value = int_var(data, key)
    return None if value is None else bool(value)


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
    #: link state per interface (wan0, wan1, sta0, wwan0), e.g. "online"
    interface_states: dict[str, str] = field(default_factory=dict)
    broadband_connected: bool | None = None
    cell_connected: bool | None = None
    low_data_mode: bool | None = None
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
        raw_flashwear = str_var(data, "/sys/pvs/flashwear_type_b", None)
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
            firmware_revision=str_var(data, "/sys/info/fwrev", None) or None,
            board_type=str_var(data, "/sys/info/boardtype", None) or None,
            usb_erase_count=int_var(data, "/sys/pvs/usb_erase_count"),
            active_interface=str_var(data, "/sys/info/active_interface", None),
            interface_states={
                name: state
                for name in INTERFACES
                if (state := str_var(data, f"/net/{name}/state", None))
                and state != "N/A"
            },
            broadband_connected=_flag(data, "/sys/toggle_cell/broadband_connected"),
            cell_connected=_flag(data, "/sys/toggle_cell/cell_connected"),
            low_data_mode=_flag(data, "/sys/toggle_cell/low_data_mode"),
            ess_reserve_soc=float_var(data, ESS_RESERVE_SOC),
            ess_control_mode=str_var(data, ESS_CONTROL_MODE, None),
        )
