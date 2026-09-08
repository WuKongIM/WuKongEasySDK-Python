import asyncio
import base64
import json
import logging
import ssl
from contextlib import asynccontextmanager

import pytest
import trustme
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from wukong_easy_sdk import (
    WKIM,
    AuthOptions,
    ErrorCode,
    WKIMChannelType,
    WKIMError,
    WKIMEvent,
    WKIMOptions,
)

pytestmark = pytest.mark.integration


@asynccontextmanager
async def endpoint(handler, **kwargs):
    async def bounded(ws):
        try:
            async with asyncio.timeout(5):
                await handler(ws)
        except ConnectionClosed:
            pass

    async with serve(bounded, "127.0.0.1", 0, ping_interval=None, **kwargs) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"{'wss' if 'ssl' in kwargs else 'ws'}://localhost:{port}/ws"


def client(url, **options):
    return WKIM(url, AuthOptions("alice", "private-token"), WKIMOptions(**options))


async def auth(ws, result=None):
    req = json.loads(await ws.recv())
    assert req["method"] == "connect"
    await reply(ws, req, {"reasonCode": 1} if result is None else result)
    return req


async def reply(ws, request, result):
    await ws.send(json.dumps({"id": request["id"], "result": result}))


def recv(payload=None, seq=18446744073709551615):
    return {
        "method": "recv",
        "params": {
            "header": {"redDot": True},
            "messageId": "9223372036854775807",
            "messageSeq": seq,
            "timestamp": 1788820000,
            "channelId": "bob",
            "channelType": 1,
            "fromUid": "bob",
            "payload": payload or {"type": 1, "content": "你好 🌍"},
        },
    }


async def test_auth_send_recv_ack_ping_custom_events_and_callback_send():
    wire = []
    acked = asyncio.Event()
    custom = asyncio.Event()
    replied = asyncio.Event()
    messages = []

    async def server(ws):
        wire.append(await auth(ws))
        # Deliver immediately after CONNECT to cover buffered response/notification ordering.
        await ws.send(json.dumps(recv()))
        await ws.send(
            json.dumps(
                {
                    "method": "event",
                    "params": {
                        "id": "ev1",
                        "type": "status",
                        "timestamp": 1788820000123,
                        "data": '{"ok":true}',
                    },
                }
            )
        )
        async for raw in ws:
            req = json.loads(raw)
            wire.append(req)
            if req["method"] == "send":
                assert json.loads(base64.b64decode(req["params"]["payload"])) == {
                    "reply": "收到 🌍"
                }
                assert req["params"]["header"]["redDot"] is False
                await reply(
                    ws,
                    req,
                    {
                        "reasonCode": 1,
                        "messageId": "9223372036854775807",
                        "messageSeq": 18446744073709551615,
                    },
                )
            elif req["method"] == "recvack":
                assert "id" not in req
                assert req["params"]["messageSeq"] == 18446744073709551615
                acked.set()
            elif req["method"] == "ping":
                await reply(ws, req, None)

    async with endpoint(server) as url:
        im = client(url)

        async def message_callback(message):
            messages.append(message)
            result = await im.send(
                "bob",
                WKIMChannelType.PERSON,
                {"reply": "收到 🌍"},
                client_msg_no="stable-id",
                header={"redDot": False},
            )
            assert result["messageSeq"] == 18446744073709551615
            replied.set()

        def custom_callback(event):
            assert event["data"] == {"ok": True}
            custom.set()

        im.on(WKIMEvent.MESSAGE, message_callback)
        im.on(WKIMEvent.CUSTOM_EVENT, custom_callback)
        async with im:
            async with asyncio.timeout(3):
                await replied.wait()
                await custom.wait()
                await acked.wait()
                await im.ping()
        assert len(messages) == 1
        assert wire[0]["params"]["deviceFlag"] == 2
        assert wire[0]["params"]["deviceId"].startswith("python_")
        assert not im.is_connected


async def test_shared_connect_cancelled_waiter_and_manual_reconnect():
    connections = []
    opened = asyncio.Event()
    release = asyncio.Event()

    async def server(ws):
        connections.append(ws)
        opened.set()
        await release.wait()
        await auth(ws)
        await ws.wait_closed()

    async with endpoint(server) as url:
        im = client(url)
        first = asyncio.create_task(im.connect())
        second = asyncio.create_task(im.connect())
        await opened.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        await second
        assert len(connections) == 1
        await asyncio.gather(im.disconnect(), im.disconnect())
        assert not im.is_connected
        await im.connect()
        assert len(connections) == 2
        await asyncio.gather(im.destroy(), im.destroy())
        with pytest.raises(WKIMError):
            await im.connect()


@pytest.mark.parametrize("mode", ["reason", "rpc", "malformed"])
async def test_auth_rejection_is_terminal_and_redacted(mode):
    count = 0

    async def server(ws):
        nonlocal count
        count += 1
        req = json.loads(await ws.recv())
        if mode == "rpc":
            await ws.send(
                json.dumps(
                    {
                        "id": req["id"],
                        "error": {
                            "code": -32001,
                            "message": "private-token",
                            "data": "private-token",
                        },
                    }
                )
            )
        else:
            await reply(ws, req, {"reasonCode": 2} if mode == "reason" else {"reasonCode": True})
        await ws.wait_closed()

    async with endpoint(server) as url:
        im = client(url, reconnect_delay=0.01)
        with pytest.raises(WKIMError) as caught:
            await im.connect()
        assert caught.value.code == {"reason": 2, "rpc": -32001, "malformed": -6}[mode]
        assert "private-token" not in str(caught.value)
        assert count == 1
        await im.destroy()


async def test_connect_deadline_and_disconnect_during_auth():
    async def server(ws):
        await ws.recv()
        await ws.wait_closed()

    async with endpoint(server) as url:
        im = client(url, connect_timeout=0.05)
        with pytest.raises(WKIMError) as caught:
            await im.connect()
        assert caught.value.code == ErrorCode.TIMEOUT
        task = asyncio.create_task(im.connect())
        await asyncio.sleep(0.01)
        await im.disconnect()
        with pytest.raises(WKIMError):
            await task
        await im.destroy()


async def test_send_timeout_cancel_and_pending_bound():
    sent = asyncio.Event()

    async def server(ws):
        await auth(ws)
        async for raw in ws:
            if json.loads(raw)["method"] == "send":
                sent.set()

    async with endpoint(server) as url:
        im = client(url, max_pending_requests=1, request_timeout=0.1)
        async with im:
            task = asyncio.create_task(im.send("bob", 1, {}))
            await sent.wait()
            with pytest.raises(WKIMError) as caught:
                await im.send("bob", 1, {})
            assert caught.value.code == ErrorCode.QUEUE_FULL
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(WKIMError) as caught:
                await im.send("bob", 1, {})
            assert caught.value.code == ErrorCode.TIMEOUT
            assert im._session.pending == {}
            assert im._session.pending_bytes == 0


async def test_unexpected_close_reconnects_without_replaying_send():
    connects = 0
    sends = 0
    reconnected = asyncio.Event()

    async def server(ws):
        nonlocal connects, sends
        connects += 1
        await auth(ws)
        if connects == 1:
            req = json.loads(await ws.recv())
            assert req["method"] == "send"
            sends += 1
            ws.transport.abort()
        else:
            async for raw in ws:
                req = json.loads(raw)
                assert req["method"] == "ping"
                await reply(ws, req, None)

    async with endpoint(server) as url:
        im = client(url, reconnect_delay=0.01)
        im.on(WKIMEvent.CONNECT, lambda _: reconnected.set() if connects == 2 else None)
        async with im:
            with pytest.raises(WKIMError):
                await im.send("bob", 1, {})
            async with asyncio.timeout(2):
                await reconnected.wait()
            await im.ping()
            assert sends == 1
            assert connects == 2


async def test_heartbeat_requires_correlated_response_and_stops_retry_on_disconnect():
    reconnecting = asyncio.Event()
    disconnected = asyncio.Event()

    async def server(ws):
        await auth(ws)
        async for _ in ws:
            # An uncorrelated pong must not satisfy the pending ping.
            await ws.send('{"method":"pong","params":{}}')

    async with endpoint(server) as url:
        im = client(url, ping_interval=0.01, pong_timeout=0.03, reconnect_delay=10)
        im.on(WKIMEvent.RECONNECTING, lambda _: reconnecting.set())
        im.on(WKIMEvent.DISCONNECT, lambda _: disconnected.set())
        await im.connect()
        async with asyncio.timeout(2):
            await reconnecting.wait()
            await disconnected.wait()
        await im.disconnect()
        assert im._supervisor is None
        assert not im.is_connected
        await im.destroy()


@pytest.mark.parametrize(
    "frame",
    [
        {"method": "disconnect", "params": {"reasonCode": 12, "reason": "secret"}},
        {"method": "recv", "params": {}},
        [1, 2],
    ],
)
async def test_server_disconnect_and_protocol_errors_stop_reconnect(frame):
    errors = asyncio.Queue()
    reconnects = []

    async def server(ws):
        await auth(ws)
        await asyncio.sleep(0.01)
        await ws.send(json.dumps(frame))
        await ws.wait_closed()

    async with endpoint(server) as url:
        im = client(url, reconnect_delay=0.01)
        im.on(WKIMEvent.ERROR, errors.put_nowait)
        im.on(WKIMEvent.RECONNECTING, reconnects.append)
        async with im:
            error = await asyncio.wait_for(errors.get(), 2)
            assert error.code in (12, ErrorCode.PROTOCOL)
            assert not im.is_connected
            assert not reconnects


async def test_callback_error_isolation_off_and_destroy_inside_callback():
    done = asyncio.Event()
    errors = []
    removed_calls = []

    async def server(ws):
        await auth(ws)
        await ws.send(json.dumps(recv()))
        await ws.wait_closed()

    async with endpoint(server) as url:
        im = client(url)

        def fail(_):
            raise RuntimeError("private-token")

        async def close(_):
            await im.destroy()
            done.set()

        listener = im.on(WKIMEvent.MESSAGE, removed_calls.append)
        im.off(WKIMEvent.MESSAGE, listener)
        im.on(WKIMEvent.MESSAGE, fail)
        im.on(WKIMEvent.MESSAGE, close)
        im.on(WKIMEvent.ERROR, errors.append)
        await im.connect()
        await asyncio.wait_for(done.wait(), 2)
        assert not removed_calls
        assert not im.is_connected
        await im.destroy()


async def test_event_overload_closes_without_acknowledging_dropped_message():
    entered = asyncio.Event()
    release = asyncio.Event()
    acks = []

    async def server(ws):
        await auth(ws)
        await ws.send(json.dumps(recv(seq=1)))
        await entered.wait()
        for seq in range(2, 5):
            await ws.send(json.dumps(recv(seq=seq)))
        async for raw in ws:
            req = json.loads(raw)
            if req["method"] == "recvack":
                acks.append(req["params"]["messageSeq"])

    async with endpoint(server) as url:
        im = client(url, max_event_queue=1)

        async def slow(_):
            entered.set()
            await release.wait()

        im.on(WKIMEvent.MESSAGE, slow)
        await im.connect()
        async with asyncio.timeout(2):
            await entered.wait()
            await im._supervisor
        release.set()
        await im.destroy()
        assert acks == [1, 2]


async def test_tls_private_ca_and_reject_untrusted_certificate(tmp_path):
    ca = trustme.CA()
    cert = ca.issue_cert("localhost")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    cert.configure_cert(context)
    ca_file = tmp_path / "ca.pem"
    ca.cert_pem.write_to_path(ca_file)

    async def server(ws):
        await auth(ws)
        await ws.wait_closed()

    async with endpoint(server, ssl=context) as url:
        async with client(url, ca_file=str(ca_file)) as im:
            assert im.is_connected
        im = client(url)
        with pytest.raises(WKIMError) as caught:
            await im.connect()
        assert "certificate" in str(caught.value)
        await im.destroy()
        im = client(url.replace("localhost", "127.0.0.1"), ca_file=str(ca_file))
        with pytest.raises(WKIMError):
            await im.connect()
        await im.destroy()


async def test_global_debug_logging_does_not_expose_secrets(caplog):
    async def server(ws):
        await auth(ws)
        req = json.loads(await ws.recv())
        await ws.send(
            json.dumps(
                {
                    "id": req["id"],
                    "error": {"code": 128, "message": "secret-response", "data": "secret-data"},
                }
            )
        )
        await ws.wait_closed()

    async with endpoint(server) as url:
        # Suppress test-server logging; only the SDK side is under examination.
        caplog.set_level(logging.CRITICAL, logger="websockets.server")
        caplog.set_level(logging.DEBUG)
        async with client(url, debug_logging=True) as im:
            with pytest.raises(WKIMError) as caught:
                await im.send("bob", 1, {"secret-payload": True})
            assert caught.value.code == 128
        for secret in ("private-token", "secret-response", "secret-data", "secret-payload"):
            assert secret not in caplog.text


async def test_reconnect_auth_error_stops_remaining_attempts():
    attempts = 0
    errors = asyncio.Queue()

    async def server(ws):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await auth(ws)
            await asyncio.sleep(0.01)
            ws.transport.abort()
        else:
            req = json.loads(await ws.recv())
            await ws.send(
                json.dumps(
                    {
                        "id": req["id"],
                        "error": {"code": -32001, "message": "Authentication rejected"},
                    }
                )
            )
            await ws.wait_closed()

    async with endpoint(server) as url:
        im = client(url, reconnect_delay=0.01)
        im.on(WKIMEvent.ERROR, errors.put_nowait)
        async with im:
            async with asyncio.timeout(2):
                while (await errors.get()).code != -32001:
                    pass
                await im._supervisor
            assert attempts == 2


async def test_oversized_inbound_frame_is_terminal():
    errors = asyncio.Queue()

    async def server(ws):
        await auth(ws)
        await asyncio.sleep(0.01)
        await ws.send(json.dumps(recv({"large": "x" * 2000})))
        await ws.wait_closed()

    async with endpoint(server) as url:
        im = client(url, max_message_bytes=512)
        im.on(WKIMEvent.ERROR, errors.put_nowait)
        async with im:
            error = await asyncio.wait_for(errors.get(), 2)
            assert error.code == ErrorCode.PROTOCOL
            assert not im.is_connected


async def test_outbound_byte_budget_and_oversized_payload_do_not_poison_connection():
    async def server(ws):
        await auth(ws)
        async for raw in ws:
            request = json.loads(raw)
            await reply(ws, request, None)

    async with endpoint(server) as url:
        async with client(url, max_pending_bytes=512, max_message_bytes=1024) as im:
            with pytest.raises(WKIMError) as caught:
                await im.send("bob", 1, {"content": "x" * 300})
            assert caught.value.code == ErrorCode.QUEUE_FULL
            with pytest.raises(WKIMError) as caught:
                await im.send("bob", 1, {"content": "x" * 2000})
            assert caught.value.code == ErrorCode.INVALID_ARGUMENT
            await im.ping()


async def test_cancelling_error_callback_does_not_recurse():
    finished = asyncio.Event()
    calls = []

    async def server(ws):
        await auth(ws)
        await ws.send(json.dumps(recv()))
        await ws.wait_closed()

    async with endpoint(server) as url:
        im = client(url)

        def fail(_):
            raise RuntimeError("application callback failed")

        async def error_callback(error):
            calls.append(error)
            finished.set()
            raise asyncio.CancelledError

        im.on(WKIMEvent.MESSAGE, fail)
        im.on(WKIMEvent.ERROR, error_callback)
        async with im:
            await asyncio.wait_for(finished.wait(), 2)
            await asyncio.sleep(0.01)
            assert len(calls) == 1


async def test_retry_exhaustion_and_context_entry_failure_release_resources():
    attempts = 0
    errors = asyncio.Queue()

    async def server(ws):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await auth(ws)
            await asyncio.sleep(0.01)
        ws.transport.abort()

    async with endpoint(server) as url:
        im = client(url, max_reconnect_attempts=2, reconnect_delay=0.01)
        im.on(WKIMEvent.ERROR, errors.put_nowait)
        async with im:
            async with asyncio.timeout(2):
                while (await errors.get()).code != ErrorCode.RECONNECT_EXHAUSTED:
                    pass
            assert attempts == 3
        im = client(url)
        with pytest.raises(WKIMError):
            async with im:
                pytest.fail("Unexpected connection")
        assert im._destroyed
        assert im._dispatcher.done()
