"""The PVS local API pypvs uses: doc/LocalAPI.md, and the variables in
doc/varserver-variables-public-*.csv."""

from enum import StrEnum

WEBSOCKET_PORT = 9002


class _Path(StrEnum):
    """Prints like the plain string, since members end up in user data."""

    def __repr__(self) -> str:
        return repr(self.value)


class Endpoint(_Path):
    AUTH_LOGIN = "/auth?login"
    VARS = "/vars"


class Model(_Path):
    PVS5 = "PVS5"
    PVS6 = "PVS6"


class SysType(_Path):
    #: varserver's default before the PVS has set it
    UNKNOWN = "Unknown"
    PV_ONLY = "PV-only"
    STORAGE = "Storage"


class Match(_Path):
    """Prefixes for /vars?match= queries."""

    ESS = "/sys/devices/ess/"
    INVERTERS = "/sys/devices/inverter/"
    METERS = "/sys/devices/meter/"
    TRANSFER_SWITCH = "/sys/devices/transfer_switch/"
    INFO = "/sys/info"
    LIVEDATA = "/sys/livedata"


class Variable(_Path):
    #: backup reserve as a 0-1 ratio of customer state of charge
    ESS_RESERVE_SOC = "/ess/config/dcm/control_param/min_customer_soc"
    #: configured battery mode; can differ from the ESS's live opMode
    ESS_CONTROL_MODE = "/ess/config/dcm/mode_param/control_mode"

    ACTIVE_INTERFACE = "/sys/info/active_interface"
    BOARDTYPE = "/sys/info/boardtype"
    CPU_USAGE = "/sys/info/cpu_usage"
    FLASH_USAGE = "/sys/info/flash_usage"
    #: firmware revision, may be empty; SW_REV is the software version
    FWREV = "/sys/info/fwrev"
    #: hardware revision, e.g. "6.02"
    HWREV = "/sys/info/hwrev"
    #: LAN0 MAC address
    LMAC = "/sys/info/lmac"
    MODEL = "/sys/info/model"
    RAM_USAGE = "/sys/info/ram_usage"
    SERIALNUM = "/sys/info/serialnum"
    #: PVS software version, e.g. "2025.10.20.61846"
    SW_REV = "/sys/info/sw_rev"
    #: PV-only or storage
    SYS_TYPE = "/sys/info/sys_type"
    #: seconds since boot
    UPTIME = "/sys/info/uptime"

    # kW and kWh; net is positive importing, ess positive discharging
    LIVEDATA_ESS_EN = "/sys/livedata/ess_en"
    LIVEDATA_ESS_P = "/sys/livedata/ess_p"
    LIVEDATA_NET_EN = "/sys/livedata/net_en"
    LIVEDATA_NET_P = "/sys/livedata/net_p"
    LIVEDATA_PV_EN = "/sys/livedata/pv_en"
    LIVEDATA_PV_P = "/sys/livedata/pv_p"
    LIVEDATA_SITE_LOAD_EN = "/sys/livedata/site_load_en"
    LIVEDATA_SITE_LOAD_P = "/sys/livedata/site_load_p"
    #: minutes
    LIVEDATA_BACKUP_TIME_REMAINING = "/sys/livedata/backupTimeRemaining"
    #: microgrid interconnect device state
    LIVEDATA_MIDSTATE = "/sys/livedata/midstate"
    #: battery state of charge as 0-1, though the docs say %
    LIVEDATA_SOC = "/sys/livedata/soc"
    #: Unix time, in seconds or milliseconds
    LIVEDATA_TIME = "/sys/livedata/time"

    #: eMMC lifetime used, in hex tenths (0x1 is 10%)
    FLASHWEAR = "/sys/pvs/flashwear_type_b"
    #: SMART attribute 229 erase count of the USB drive
    USB_ERASE_COUNT = "/sys/pvs/usb_erase_count"

    #: set to 1 to start the telemetry websocket
    TELEMETRYWS_ENABLE = "/sys/telemetryws/enable"

    BROADBAND_CONNECTED = "/sys/toggle_cell/broadband_connected"
    CELL_CONNECTED = "/sys/toggle_cell/cell_connected"
    LOW_DATA_MODE = "/sys/toggle_cell/low_data_mode"


def net_state(interface: str) -> str:
    """The link state variable of a network interface."""
    return f"/net/{interface}/state"


INTERFACES_BY_MODEL = {
    Model.PVS5: ("cell", "plc", "sta0", "wan"),
    Model.PVS6: ("sta0", "wan0", "wan1", "wwan0"),
}
#: not in the PVS5's variables
PVS6_ONLY_VARIABLES = frozenset(
    {
        Variable.ESS_CONTROL_MODE,
        Variable.ESS_RESERVE_SOC,
        Variable.FLASHWEAR,
        Variable.TELEMETRYWS_ENABLE,
        Variable.USB_ERASE_COUNT,
    }
)
