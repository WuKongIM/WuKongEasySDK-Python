"""Bounded JSON-RPC codec. Public message dictionaries retain JS field names."""

import base64
import binascii
import json
from typing import Any

from .types import ErrorCode, WKIMError


def encode(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise WKIMError(ErrorCode.INVALID_ARGUMENT, "Value must be finite JSON") from None


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-finite JSON")


def loads(value: str | bytes) -> Any:
    return json.loads(value, parse_constant=_invalid_constant)


def decode_frame(raw: str | bytes) -> dict[str, Any]:
    try:
        frame = loads(raw)
        if not isinstance(frame, dict):
            raise ValueError("Object required")
        if "jsonrpc" in frame and frame["jsonrpc"] != "2.0":
            raise ValueError("Invalid version")
        return frame
    except (ValueError, UnicodeError, RecursionError):
        raise WKIMError(ErrorCode.PROTOCOL, "Invalid JSON-RPC frame") from None


def encode_payload(payload: dict[str, Any] | list[Any]) -> str:
    if not isinstance(payload, (dict, list)):
        raise WKIMError(ErrorCode.INVALID_ARGUMENT, "Payload must be an object or array")
    try:
        return base64.b64encode(encode(payload).encode("utf-8")).decode("ascii")
    except UnicodeError:
        raise WKIMError(ErrorCode.INVALID_ARGUMENT, "Payload must be valid UTF-8") from None


def decode_payload(payload: Any) -> Any:
    if not isinstance(payload, str):
        return payload
    # Accept the Product Gateway object profile, JSON text, and the JS Base64 profile.
    try:
        return loads(payload)
    except (ValueError, RecursionError):
        pass
    try:
        return loads(base64.b64decode(payload, validate=True))
    except (ValueError, UnicodeError, binascii.Error, RecursionError):
        return payload


def message_identity(params: dict[str, Any]) -> None:
    """Normalize decimal message IDs without ever passing through floating point."""
    mid = params.get("messageId")
    seq = params.get("messageSeq")
    if type(mid) is int and mid >= 0:
        params["messageId"] = str(mid)
    elif not isinstance(mid, str) or not mid:
        raise WKIMError(ErrorCode.PROTOCOL, "Invalid message ID")
    if type(seq) is not int or not 0 <= seq < 2**64:
        raise WKIMError(ErrorCode.PROTOCOL, "Invalid message sequence")


def successful_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict) or type(result.get("reasonCode")) is not int:
        raise WKIMError(ErrorCode.PROTOCOL, "Invalid operation result")
    if result["reasonCode"] != 1:
        raise WKIMError(result["reasonCode"], "Server rejected operation")
    return result
