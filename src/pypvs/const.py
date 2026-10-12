import enum


class SupportedFeatures(enum.IntFlag):
    """Features available from the PVS. Features form a bitmask."""

    GATEWAY = 1  #: The PVS itself is the gateway
    INVERTERS = 2  #: PVS reports inverters
    METERING = 4  #: PVS reports active production meter
    ESS = 8  #: PVS reports energy storage system
    TRANSFER_SWITCH = 16  #: PVS reports transfer switch
