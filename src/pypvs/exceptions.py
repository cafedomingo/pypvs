class PVSError(Exception):
    """Base class for PVS exceptions."""


class PVSFirmwareCheckError(PVSError):
    """Exception raised when unable to query the PVS firmware version."""


class PVSAuthenticationError(PVSError):
    """Exception raised when unable to get a session if from the PVS."""


class PVSProbeFailed(PVSError):
    """Exception raised when the PVS probe fails."""


class PVSCommunicationError(PVSError):
    """Exception raised when the PVS communication fails.

    `status` is the HTTP status the PVS answered with, or None when it was
    not reached (timeout, connection error).
    """

    def __init__(self, message: str = "", status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class PVSDataFormatError(PVSError):
    """Exception raised when the PVS data format is incorrect."""


ENDPOINT_PROBE_EXCEPTIONS = (
    PVSDataFormatError,
    PVSAuthenticationError,
    PVSProbeFailed,
    PVSCommunicationError,
    KeyError,
)
