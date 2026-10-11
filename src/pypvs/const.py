import enum

# System Production
VARS_MATCH_INVERTERS = "/sys/devices/inverter/"
VARS_MATCH_METERS = "/sys/devices/meter/"
VARS_MATCH_ESS = "/sys/devices/ess/"
VARS_MATCH_TRANSFER_SWITCH = "/sys/devices/transfer_switch/"
VARS_MATCH_INFO = "/sys/info"
VAR_UPTIME = "/sys/info/uptime"


class SupportedFeatures(enum.IntFlag):
    """Features available from the PVS. Features form a bitmask."""

    GATEWAY = 1  #: The PVS itself is the gateway
    INVERTERS = 2  #: PVS reports inverters
    METERING = 4  #: PVS reports active production meter
    ESS = 8  #: PVS reports energy storage system
    TRANSFER_SWITCH = 16  #: PVS reports transfer switch
