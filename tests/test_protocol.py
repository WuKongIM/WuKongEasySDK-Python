import math

import pytest

from wukong_easy_sdk import WKIM, AuthOptions, ErrorCode, WKIMError, WKIMOptions
from wukong_easy_sdk.protocol import (
    decode_frame,
    decode_payload,
    encode_payload,
    message_identity,
    successful_result,
)


@pytest.mark.parametrize("payload", [{"type": 1, "content": "你好 🌍"}, [1, "a", None], {}])
def test_payload_profiles(payload):
    import json

    assert decode_payload(encode_payload(payload)) == payload
    assert decode_payload(json.dumps(payload)) == payload
    assert decode_payload(payload) == payload


@pytest.mark.parametrize("payload", [None, "text", 1, {"bad": math.nan}, {"bad": {1, 2}}])
def test_invalid_outbound_payload(payload):
    with pytest.raises(WKIMError) as caught:
        encode_payload(payload)
    assert caught.value.code == ErrorCode.INVALID_ARGUMENT


@pytest.mark.parametrize("raw", ["[]", "null", "{", '{"value":NaN}', '{"jsonrpc":"1.0"}', b"\xff"])
def test_bad_frames(raw):
    with pytest.raises(WKIMError) as caught:
        decode_frame(raw)
    assert caught.value.code == ErrorCode.PROTOCOL


def test_preserve_unknown_payload_and_u64_identity():
    assert decode_payload("plain text") == "plain text"
    message = {"messageId": 18446744073709551615, "messageSeq": 18446744073709551615}
    message_identity(message)
    assert message["messageId"] == "18446744073709551615"
    assert message["messageSeq"] == 18446744073709551615


@pytest.mark.parametrize("seq", [True, -1, 1.5, "1", 2**64])
def test_invalid_sequence(seq):
    with pytest.raises(WKIMError):
        message_identity({"messageId": "1", "messageSeq": seq})


def test_result_reason_is_checked_and_redacted():
    with pytest.raises(WKIMError) as caught:
        successful_result({"reasonCode": 128, "secret": "must-not-leak"})
    assert caught.value.code == 128
    assert "must-not-leak" not in str(caught.value)
    with pytest.raises(WKIMError):
        successful_result({"reasonCode": True})


@pytest.mark.parametrize(
    "options",
    [
        {"request_timeout": 0},
        {"ping_interval": float("inf")},
        {"max_event_queue": 0},
        {"max_pending_requests": True},
        {"max_reconnect_attempts": -1},
    ],
)
def test_option_bounds(options):
    with pytest.raises(ValueError):
        WKIMOptions(**options)


@pytest.mark.parametrize("url", ["http://localhost", "ws:///", "ws://u:p@host", "ws://x/#f"])
def test_url_validation(url):
    with pytest.raises(ValueError):
        WKIM(url, AuthOptions("alice", "secret"))


def test_auth_repr_and_device_defaults():
    auth = AuthOptions("alice", "must-not-leak")
    assert "must-not-leak" not in repr(auth)
    assert auth.device_flag == 2
    with pytest.raises(ValueError):
        AuthOptions("alice", "token", device_flag=True)
