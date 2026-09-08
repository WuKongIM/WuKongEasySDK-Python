"""WuKongEasySDK-Python: a typed asyncio client for lightweight online messaging."""

from .client import WKIM, EventHandler
from .types import (
    AuthOptions,
    ConnectResult,
    ErrorCode,
    EventNotification,
    Header,
    MessageSetting,
    ReasonCode,
    RecvMessage,
    SendResult,
    WKIMChannelType,
    WKIMDeviceFlag,
    WKIMError,
    WKIMEvent,
    WKIMOptions,
)

__version__ = "0.1.0"

__all__ = [
    "WKIM",
    "AuthOptions",
    "WKIMOptions",
    "WKIMChannelType",
    "WKIMDeviceFlag",
    "WKIMEvent",
    "WKIMError",
    "ErrorCode",
    "ReasonCode",
    "Header",
    "MessageSetting",
    "ConnectResult",
    "SendResult",
    "RecvMessage",
    "EventNotification",
    "EventHandler",
    "__version__",
]
