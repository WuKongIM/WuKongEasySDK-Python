# WuKongEasySDK-Python

[中文 README](https://github.com/WuKongIM/WuKongEasySDK-Python/blob/main/README_zh.md)

A typed Python 3.11+ `asyncio` client for WuKongIM's lightweight WebSocket
JSON-RPC messaging path. It follows [WuKongEasySDK-JS 2.0.4](https://github.com/WuKongIM/WuKongEasySDK-JS/tree/9c03c98c725982fac224cd1d3b52456eae983975):
CONNECT authentication, online SEND/SENDACK and RECV/RECVACK, JSON-RPC heartbeats,
bounded reconnect, and custom event notifications. Supports WS and verified WSS.

## Install

Install exact version **0.1.0** from [PyPI](https://pypi.org/project/wukong-easy-sdk/0.1.0/):

```sh
python3 -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
source .venv/bin/activate
python -m pip install --index-url https://pypi.org/simple "wukong-easy-sdk==0.1.0"
```

The distribution name is `wukong-easy-sdk`; the import is `wukong_easy_sdk`.
Runtime dependency: `websockets>=15.0.1,<18`. `uv.lock` pins development dependencies.

To run the interactive example with the installed package, download its matching source:

```sh
git clone --branch v0.1.0 --depth 1 https://github.com/WuKongIM/WuKongEasySDK-Python.git
python WuKongEasySDK-Python/examples/chat.py
```

Supply `WKIM_UID`, `WKIM_TOKEN`, `WKIM_PEER`, and `WKIM_URL` through the environment.
For a source installation, check out the exact tag or tested commit and run
`python -m pip install ./WuKongEasySDK-Python`.

## Connect and send

Your trusted backend must supply each user's UID, Token and reachable Gateway URL.
The SDK defaults to DESKTOP/PC `2`; provision the Token for the same device flag
(APP `0`, WEB `1`, DESKTOP `2`). Never call Product HTTP management from an untrusted client.
The default development URL is `ws://127.0.0.1:5200`; use `/ws` only when configured
on the listener or proxy. Use `wss://` in production.

```python
import asyncio
import os

from wukong_easy_sdk import AuthOptions, WKIM, WKIMChannelType, WKIMEvent


async def main():
    im = WKIM.init(
        os.environ.get("WKIM_URL", "ws://127.0.0.1:5200"),
        AuthOptions(uid="alice", token=os.environ["WKIM_TOKEN"]),
    )

    def receive(message):
        # Pass message["payload"] to your application's UI or bounded queue.
        # Do not log entire messages in production.
        pass

    listener = im.on(WKIMEvent.MESSAGE, receive)
    im.on(WKIMEvent.ERROR, lambda error: print("EasySDK operation failed"))
    async with im:  # waits for authentication; always destroys on exit
        ack = await im.send(
            "bob", WKIMChannelType.PERSON, {"type": 1, "content": "Hello from Python!"}
        )
        assert ack["reasonCode"] == 1
        # Bob must already be connected. Keep receiving until the application stops.
        await asyncio.sleep(10)
    im.off(WKIMEvent.MESSAGE, listener)


asyncio.run(main())
```

Run two terminals with different `WKIM_UID`, `WKIM_TOKEN`, and `WKIM_PEER`
environment variables, then `python examples/chat.py`. Both peers must be online.
The example intentionally displays chat content; the SDK itself is silent.

## API and lifecycle

| API | Contract |
| --- | --- |
| `WKIM(url, AuthOptions(...), WKIMOptions(...))` / `WKIM.init(...)` | Independent instances; no global singleton |
| `await connect()` | Return authenticated CONNECT result; concurrent callers share an attempt |
| `await send(channel_id, channel_type, payload, ...)` | Return SENDACK or raise `WKIMError`; Payload is a JSON object or array |
| `await ping()` | Require the same response ID; `result: null` is valid |
| `on(event, callback)` / `off(event, callback)` | Synchronous or async handlers; keep returned callback for removal |
| `is_connected` | True only after authentication |
| `await disconnect()` | Stop connection, pending requests, heartbeat and retry; can connect again |
| `await destroy()` | Permanent shutdown and listener cleanup; idempotent |
| `async with im` | Connect on entry, destroy on exit (including failed entry) |

One instance belongs to one asyncio loop, never to multiple threads or event loops.
Callbacks run serially in a separate dispatcher, so an async message callback can
`await im.send(...)`, `await im.disconnect()`, or `await im.destroy()`. Do not block
the event loop or await another event from the same serial dispatcher. Remove
listeners and close the old instance before switching credentials. Cancelling a
`connect()` waiter leaves the shared connection attempt running; call `disconnect()`
to cancel it. Cancelled or timed-out sends are removed from pending requests.

Python options and parameters use snake_case. Received dictionaries keep JS
camelCase keys: `messageId` (string), `messageSeq` (full precision integer),
`channelId`, `channelType`, `fromUid`, `timestamp` (seconds), `payload`, `header`,
optional `clientMsgNo` and `setting`. Object, JSON-text and Base64 JSON Payloads
are decoded. Unknown plain strings are preserved. Custom events carry `id`,
`type`, `timestamp` (milliseconds), `data` (JSON text is parsed), optional `header`.

`send()` supports keyword arguments `client_msg_no`, `header`, `setting`, and
`topic`. Header flags are `noPersist`, `redDot`, `syncOnce`, `dup`; `redDot` defaults
to true but an explicit false is respected. Setting flags are `receipt`, `signal`,
`stream`, `topic`. Server support remains authoritative for optional flags and
channel types. Group membership must be established by your backend.

Events: `CONNECT`, `DISCONNECT`, `MESSAGE`, `ERROR`, `SEND_ACK`, `RECONNECTING`,
`CUSTOM_EVENT` (`WKIMEvent`). `SEND_ACK` accompanies successful send completion.
Error text is sanitized; `WKIMError.code` preserves server codes (including JSON-RPC
negative codes) or a local `ErrorCode`. Callback errors do not kill the receiver.
DISCONNECT reports a numeric `reasonCode`; local/network failures use local codes.
RECONNECTING carries `attempt` and `delay` in seconds.

## Reliability, bounds and TLS

- CONNECT deadline includes TCP/TLS/WebSocket and authentication: 10 seconds.
  Requests: 15 seconds; heartbeat interval: 25 seconds; Pong timeout: 10 seconds;
  close timeout: 2 seconds. All are configurable in `WKIMOptions`.
- After an authenticated session loses transport, retry up to 5 times with
  exponential delay from 1 second, capped at 30 seconds, with 20% jitter.
  First-connect failure, auth rejection, server disconnect, protocol errors,
  event overload, certificate verification failure and manual shutdown stop retry.
- Up to 1,024 pending requests, 4 MiB serialized pending request bytes, 1 MiB per
  wire message, and 256 queued events with a 4 MiB wire-size budget (also counting
  the executing event). Python object overhead is additional. Inbound WebSocket
  buffering is 16 frames with a 32 KiB write high-water mark. Pending saturation
  raises `QUEUE_FULL`. Event saturation closes the session; events that cannot
  enter the queue are not acknowledged. Lifecycle notifications are best effort
  when overloaded. Keep callbacks short and use application backpressure.
- RECVACK is sent after the notification enters the dispatcher, independently of
  application processing. It is neither a read receipt nor a durable business ack.
  Duplicate delivery is possible; deduplicate by message identity when required.
- No automatic SEND replay, offline queue, history sync, conversations, unread
  counts, subscriptions, push, or general RPC API. A timeout or lost SENDACK may
  have an unknown commit outcome: retain `client_msg_no` and reconcile through
  your backend before deciding to retry.
- WSS verifies the certificate chain and hostname using system trust, minimum
  TLS 1.2. For a private CA, use `WKIMOptions(ca_file="/path/ca.pem")`. There is no
  TLS verification bypass. Automatic system proxy discovery is disabled; supply
  the reachable Gateway/proxy endpoint directly.
- SDK logging is off by default. `debug_logging=True` enables only fixed lifecycle
  metadata under the `wukong_easy_sdk` logger. Tokens, URLs, Payloads, raw frames,
  peer response text and underlying exception objects are never logged by the SDK,
  even when the application enables global DEBUG logging.

## Development and validation

```sh
uv sync --locked
uv run pytest                         # fast codec and option tests
uv run pytest -m integration          # bounded local WS/WSS and lifecycle tests
uv run ruff check .
uv run mypy
uv build                             # sdist and wheel
# Explicit black-box product acceptance (no cloud resources):
uv run python tests/product.py --server /absolute/path/to/wukongim \
  --js-entry /absolute/path/to/WuKongEasySDK-JS/dist/cjs/index.js
```

See [validation evidence](https://github.com/WuKongIM/WuKongEasySDK-Python/blob/main/docs/VALIDATION.md) for exact tested revisions and limits,
and [API migration from JS](https://github.com/WuKongIM/WuKongEasySDK-Python/blob/v0.1.0/docs/API.md) for the mapping.
