"""Public options and wire constants aligned with WuKongEasySDK-JS 2.0.4."""

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from math import isfinite
from typing import Any, NotRequired, TypedDict


class WKIMChannelType(IntEnum):
    PERSON = 1
    GROUP = 2
    CUSTOMER_SERVICE = 3
    COMMUNITY = 4
    COMMUNITY_TOPIC = 5
    INFO = 6
    DATA = 7
    TEMP = 8
    LIVE = 9
    VISITORS = 10


class WKIMDeviceFlag(IntEnum):
    APP = 0
    WEB = 1
    DESKTOP = 2


class WKIMEvent(StrEnum):
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    MESSAGE = "message"
    ERROR = "error"
    SEND_ACK = "sendack"
    RECONNECTING = "reconnecting"
    CUSTOM_EVENT = "customevent"


class ReasonCode(IntEnum):
    UNKNOWN = 0
    SUCCESS = 1
    AUTH_FAIL = 2
    SUBSCRIBER_NOT_EXIST = 3
    IN_BLACKLIST = 4
    CHANNEL_NOT_EXIST = 5
    USER_NOT_ON_NODE = 6
    SENDER_OFFLINE = 7
    MSG_KEY_ERROR = 8
    PAYLOAD_DECODE_ERROR = 9
    FORWARD_SEND_PACKET_ERROR = 10
    NOT_ALLOW_SEND = 11
    CONNECT_KICK = 12
    NOT_IN_WHITELIST = 13
    QUERY_TOKEN_ERROR = 14
    SYSTEM_ERROR = 15
    CHANNEL_ID_ERROR = 16
    NODE_MATCH_ERROR = 17
    NODE_NOT_MATCH = 18
    BAN = 19
    NOT_SUPPORT_HEADER = 20
    CLIENT_KEY_IS_EMPTY = 21
    RATE_LIMIT = 22
    NOT_SUPPORT_CHANNEL_TYPE = 23
    DISBAND = 24
    SEND_BAN = 25


class ErrorCode(IntEnum):
    INVALID_ARGUMENT = -1
    NOT_CONNECTED = -2
    CLOSED = -3
    TIMEOUT = -4
    CONNECTION_LOST = -5
    PROTOCOL = -6
    QUEUE_FULL = -7
    CALLBACK = -8
    RECONNECT_EXHAUSTED = -9


class WKIMError(Exception):
    """Safe error text with a local negative code or the original server code."""

    def __init__(self, code: int, message: str) -> None:
        self.code = int(code)
        super().__init__(message)


@dataclass(frozen=True)
class AuthOptions:
    """One identity; token is excluded from repr and must match device_flag."""

    uid: str
    token: str = field(repr=False)
    device_id: str = ""
    device_flag: WKIMDeviceFlag = WKIMDeviceFlag.DESKTOP

    def __post_init__(self) -> None:
        if not isinstance(self.uid, str) or not self.uid:
            raise ValueError("uid must be a nonempty string")
        if not isinstance(self.token, str) or not self.token:
            raise ValueError("token must be a nonempty string")
        if not isinstance(self.device_id, str):
            raise ValueError("device_id must be a string")
        if isinstance(self.device_flag, bool) or self.device_flag not in (0, 1, 2):
            raise ValueError("device_flag must be APP=0, WEB=1, or DESKTOP=2")


@dataclass(frozen=True)
class WKIMOptions:
    """All durations are seconds; queues have explicit count and byte bounds."""

    connect_timeout: float = 10
    request_timeout: float = 15
    ping_interval: float = 25
    pong_timeout: float = 10
    close_timeout: float = 2
    max_reconnect_attempts: int = 5
    reconnect_delay: float = 1
    max_reconnect_delay: float = 30
    max_pending_requests: int = 1024
    max_pending_bytes: int = 4 * 1024 * 1024
    max_message_bytes: int = 1024 * 1024
    max_event_queue: int = 256
    max_event_bytes: int = 4 * 1024 * 1024
    ca_file: str | None = None
    debug_logging: bool = False

    def __post_init__(self) -> None:
        for name in (
            "connect_timeout",
            "request_timeout",
            "ping_interval",
            "pong_timeout",
            "close_timeout",
            "reconnect_delay",
            "max_reconnect_delay",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a positive finite number")
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        for name in (
            "max_pending_requests",
            "max_pending_bytes",
            "max_message_bytes",
            "max_event_queue",
            "max_event_bytes",
            "max_reconnect_attempts",
        ):
            value = getattr(self, name)
            minimum = 0 if name == "max_reconnect_attempts" else 1
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} is outside its integer bounds")


class Header(TypedDict, total=False):
    noPersist: bool
    redDot: bool
    syncOnce: bool
    dup: bool


class MessageSetting(TypedDict, total=False):
    receipt: bool
    signal: bool
    stream: bool
    topic: bool


class ConnectResult(TypedDict):
    reasonCode: int
    serverKey: NotRequired[str]
    salt: NotRequired[str]
    timeDiff: NotRequired[int]
    serverVersion: NotRequired[int]
    nodeId: NotRequired[int]


class SendResult(TypedDict):
    messageId: str
    messageSeq: int
    reasonCode: int


class RecvMessage(TypedDict):
    header: Header
    messageId: str
    messageSeq: int
    timestamp: int
    channelId: str
    channelType: int
    fromUid: str
    payload: Any
    clientMsgNo: NotRequired[str]
    setting: NotRequired[MessageSetting]


class EventNotification(TypedDict):
    id: str
    type: str
    timestamp: int
    data: Any
    header: NotRequired[Header]
