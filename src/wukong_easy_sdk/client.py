"""An asyncio-owned client with one supervisor and session-scoped requests."""

import asyncio
import inspect
import logging
import random
import ssl
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlsplit

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from .protocol import (
    decode_frame,
    decode_payload,
    encode,
    encode_payload,
    loads,
    message_identity,
    successful_result,
)
from .types import (
    AuthOptions,
    ConnectResult,
    ErrorCode,
    Header,
    MessageSetting,
    SendResult,
    WKIMChannelType,
    WKIMDeviceFlag,
    WKIMError,
    WKIMEvent,
    WKIMOptions,
)

EventHandler = Callable[[Any], Awaitable[None] | None]

# Independent from the logging registry: application DEBUG settings cannot expose frames.
_wire_logger = logging.Logger("wukong_easy_sdk.transport", level=logging.CRITICAL + 1)
_wire_logger.disabled = True
_logger = logging.getLogger("wukong_easy_sdk")
_logger.addHandler(logging.NullHandler())


@dataclass
class _Session:
    """Only this transport can complete its pending requests; old frames cannot cross sessions."""

    ws: ClientConnection
    pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict)
    pending_bytes: int = 0
    reader: asyncio.Task[None] | None = None
    heartbeat: asyncio.Task[None] | None = None
    failure: WKIMError | None = None
    terminal: bool = False
    connect_id: str | None = None
    auth_response: bool = False
    auth_ready: asyncio.Event = field(default_factory=asyncio.Event)


class WKIM:
    """One identity on one asyncio loop. Use an async context manager or await destroy().

    Synchronous and asynchronous callbacks run serially on a separate dispatcher;
    async callbacks may await send(). They must not block the event loop. No offline
    queue or automatic SEND replay is provided.
    """

    Event = WKIMEvent
    ChannelType = WKIMChannelType
    DeviceFlag = WKIMDeviceFlag

    def __init__(self, url: str, auth: AuthOptions, options: WKIMOptions | None = None) -> None:
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme not in ("ws", "wss")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise ValueError
            _ = parsed.port  # Trigger validation of malformed or out-of-range ports.
        except (ValueError, TypeError):
            raise ValueError(
                "A ws:// or wss:// URL without userinfo or fragment is required"
            ) from None
        if not isinstance(auth, AuthOptions):
            raise TypeError("auth must be AuthOptions")
        self._url = url
        self._auth = auth
        self.options = options or WKIMOptions()
        self._tls: ssl.SSLContext | None = None
        if parsed.scheme == "wss":
            self._tls = ssl.create_default_context(cafile=self.options.ca_file)
            self._tls.minimum_version = ssl.TLSVersion.TLSv1_2
        elif self.options.ca_file:
            raise ValueError("ca_file requires a wss:// URL")
        self._device_id = auth.device_id or f"python_{uuid.uuid4().hex}"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: _Session | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._stopping: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[ConnectResult] | None = None
        self._result: ConnectResult | None = None
        self._destroyed = False
        self._listeners: dict[WKIMEvent, list[EventHandler]] = {e: [] for e in WKIMEvent}
        # Event bytes count queued and currently executing notifications.
        self._events: asyncio.Queue[tuple[WKIMEvent, Any, int]] = asyncio.Queue(
            self.options.max_event_queue
        )
        self._event_bytes = 0
        self._dispatcher: asyncio.Task[None] | None = None

    @classmethod
    def init(cls, url: str, auth: AuthOptions, options: WKIMOptions | None = None) -> "WKIM":
        """JS-style construction, with independent instances instead of a global singleton."""
        return cls(url, auth, options)

    @property
    def is_connected(self) -> bool:
        """True only after CONNECT authentication succeeds on the current socket."""
        return self._result is not None

    def on(self, event: WKIMEvent | str, callback: EventHandler) -> EventHandler:
        """Register a callback once; retain the returned callback for off()."""
        if self._destroyed:
            raise WKIMError(ErrorCode.CLOSED, "Client is destroyed")
        if not callable(callback):
            raise TypeError("callback must be callable")
        listeners = self._listeners[WKIMEvent(event)]
        if callback not in listeners:
            listeners.append(callback)
        return callback

    def off(self, event: WKIMEvent | str, callback: EventHandler) -> None:
        """Remove a listener. A callback already executing may finish."""
        listeners = self._listeners[WKIMEvent(event)]
        if callback in listeners:
            listeners.remove(callback)

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("Use each WKIM instance on one asyncio event loop")
        self._loop = loop

    async def connect(self) -> ConnectResult:
        """Wait for authentication. Concurrent callers share one connection attempt.

        Cancelling a waiter does not cancel other waiters or the shared attempt;
        call disconnect() to stop it. An initial failure is returned without retry.
        """
        self._bind_loop()
        if self._destroyed:
            raise WKIMError(ErrorCode.CLOSED, "Client is destroyed")
        if self._stopping is not None and not self._stopping.done():
            raise WKIMError(ErrorCode.CLOSED, "Client is disconnecting")
        if self._result is not None:
            return dict(self._result)  # type: ignore[return-value]
        if self._dispatcher is None or self._dispatcher.done():
            self._dispatcher = asyncio.create_task(self._dispatch(), name="wkim-events")
        if self._ready is None or self._ready.done():
            self._ready = asyncio.get_running_loop().create_future()
            # A cancelled waiter may leave no consumer; still retrieve eventual failures.
            self._ready.add_done_callback(lambda f: None if f.cancelled() else f.exception())
        if self._supervisor is None or self._supervisor.done():
            self._supervisor = asyncio.create_task(self._run(), name="wkim-connection")
        return await asyncio.shield(self._ready)

    async def disconnect(self) -> None:
        """Cancel connection, requests, heartbeat, and retries; the instance remains reusable."""
        self._bind_loop()
        if self._stopping is None or self._stopping.done():
            self._stopping = asyncio.create_task(self._stop(), name="wkim-stop")
        await asyncio.shield(self._stopping)

    async def _stop(self) -> None:
        task = self._supervisor
        self._result = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._supervisor = None
        self._fail_ready(WKIMError(ErrorCode.CLOSED, "Client disconnected"))

    async def destroy(self) -> None:
        """Permanently close and release listeners. Safe to call from an async callback."""
        self._bind_loop()
        self._destroyed = True
        await self.disconnect()
        for listeners in self._listeners.values():
            listeners.clear()
        dispatcher = self._dispatcher
        if dispatcher is not None and dispatcher is not asyncio.current_task():
            dispatcher.cancel()
            await asyncio.gather(dispatcher, return_exceptions=True)
        while not self._events.empty():
            _, _, size = self._events.get_nowait()
            self._event_bytes -= size

    async def __aenter__(self) -> "WKIM":
        try:
            await self.connect()
        except BaseException:
            await self.destroy()
            raise
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.destroy()

    async def send(
        self,
        channel_id: str,
        channel_type: WKIMChannelType | int,
        payload: dict[str, Any] | list[Any],
        *,
        client_msg_no: str | None = None,
        header: Header | None = None,
        setting: MessageSetting | None = None,
        topic: str | None = None,
    ) -> SendResult:
        """Return SENDACK without replay; retain client_msg_no to reconcile uncertain outcomes."""
        self._bind_loop()
        session = self._session
        if not self.is_connected or session is None:
            raise WKIMError(ErrorCode.NOT_CONNECTED, "Call connect() before sending")
        if not isinstance(channel_id, str) or not channel_id:
            raise WKIMError(ErrorCode.INVALID_ARGUMENT, "channel_id must be nonempty")
        if (
            not isinstance(channel_type, int)
            or isinstance(channel_type, bool)
            or not 1 <= channel_type <= 255
        ):
            raise WKIMError(ErrorCode.INVALID_ARGUMENT, "channel_type must be in 1..255")
        if client_msg_no is not None and (not isinstance(client_msg_no, str) or not client_msg_no):
            raise WKIMError(ErrorCode.INVALID_ARGUMENT, "client_msg_no must be nonempty")
        if topic is not None and not isinstance(topic, str):
            raise WKIMError(ErrorCode.INVALID_ARGUMENT, "topic must be a string")
        for flags, allowed in (
            (header, {"noPersist", "redDot", "syncOnce", "dup"}),
            (setting, {"receipt", "signal", "stream", "topic"}),
        ):
            if flags is not None and (
                not isinstance(flags, dict)
                or any(k not in allowed or type(v) is not bool for k, v in flags.items())
            ):
                raise WKIMError(ErrorCode.INVALID_ARGUMENT, "Invalid message flags")
        params: dict[str, Any] = {
            "channelId": channel_id,
            "channelType": int(channel_type),
            "clientMsgNo": client_msg_no or str(uuid.uuid4()),
            "payload": encode_payload(payload),
            "header": {"redDot": True, **(header or {})},
        }
        if setting is not None:
            params["setting"] = dict(setting)
        if topic is not None:
            params["topic"] = topic
        result = successful_result(await self._request(session, "send", params))
        message_identity(result)
        self._emit_safe(WKIMEvent.SEND_ACK, dict(result))
        return cast(SendResult, result)

    async def ping(self) -> None:
        """Require a response with the same request ID, including a valid result: null."""
        self._bind_loop()
        session = self._session
        if not self.is_connected or session is None:
            raise WKIMError(ErrorCode.NOT_CONNECTED, "Call connect() before ping")
        await self._request(session, "ping", {}, self.options.pong_timeout)

    def _fail_ready(self, error: WKIMError) -> None:
        if self._ready is not None and not self._ready.done():
            self._ready.set_exception(error)

    async def _run(self) -> None:
        """Own transport replacement sequentially; clean the previous session before retrying."""
        previously_connected = False
        attempts = 0
        try:
            while True:
                session: _Session | None = None
                error = WKIMError(ErrorCode.CONNECTION_LOST, "Connection lost")
                authenticated = False
                terminal = False
                try:
                    async with asyncio.timeout(self.options.connect_timeout):
                        kwargs: dict[str, Any] = {}
                        if self._tls is not None:
                            kwargs["ssl"] = self._tls
                        ws = await connect(
                            self._url,
                            ping_interval=None,
                            compression=None,
                            proxy=None,
                            open_timeout=self.options.connect_timeout,
                            close_timeout=self.options.close_timeout,
                            max_size=self.options.max_message_bytes,
                            max_queue=16,
                            write_limit=32768,
                            logger=_wire_logger,
                            **kwargs,
                        )
                        session = _Session(ws)
                        self._session = session
                        session.reader = asyncio.create_task(self._read(session), name="wkim-read")
                        result = successful_result(
                            await self._request(
                                session,
                                "connect",
                                {
                                    "uid": self._auth.uid,
                                    "token": self._auth.token,
                                    "deviceId": self._device_id,
                                    "deviceFlag": int(self._auth.device_flag),
                                    "clientTimestamp": time.time_ns() // 1_000_000,
                                },
                                self.options.connect_timeout,
                            )
                        )
                    # A CONNECT reply followed immediately by a close cannot activate a dead socket.
                    if session.reader.done():
                        await session.reader
                        raise WKIMError(
                            ErrorCode.CONNECTION_LOST, "Connection closed during CONNECT"
                        )
                    self._result = cast(ConnectResult, result)
                    session.auth_ready.set()
                    authenticated = previously_connected = True
                    attempts = 0
                    self._emit(WKIMEvent.CONNECT, dict(result))
                    if self._ready is not None and not self._ready.done():
                        self._ready.set_result(cast(ConnectResult, dict(result)))
                    session.heartbeat = asyncio.create_task(
                        self._heartbeat(session), name="wkim-ping"
                    )
                    await session.reader
                    if session.failure is not None:
                        error = session.failure
                except asyncio.CancelledError:
                    error = WKIMError(ErrorCode.CLOSED, "Client disconnected")
                    raise
                except WKIMError as exc:
                    error = exc
                    terminal = (
                        exc.code in (ErrorCode.PROTOCOL, ErrorCode.QUEUE_FULL) or exc.code >= 0
                    )
                except TimeoutError:
                    error = WKIMError(ErrorCode.TIMEOUT, "Connection timed out")
                except ssl.SSLCertVerificationError:
                    error = WKIMError(
                        ErrorCode.CONNECTION_LOST, "TLS certificate verification failed"
                    )
                    terminal = True
                except Exception:
                    # Do not expose URLs, raw peer responses, or lower-level exception strings.
                    error = (session.failure if session is not None else None) or WKIMError(
                        ErrorCode.CONNECTION_LOST, "WebSocket connection failed"
                    )
                finally:
                    self._result = None
                    self._session = None
                    if session is not None:
                        terminal = terminal or session.terminal
                        await self._clean_session(session, error)
                    if authenticated:
                        self._emit_safe(WKIMEvent.DISCONNECT, {"reasonCode": error.code})
                self._emit_safe(WKIMEvent.ERROR, error)
                if not previously_connected or terminal:
                    self._fail_ready(error)
                    return
                if attempts >= self.options.max_reconnect_attempts:
                    error = WKIMError(ErrorCode.RECONNECT_EXHAUSTED, "Reconnect attempts exhausted")
                    self._emit_safe(WKIMEvent.ERROR, error)
                    self._fail_ready(error)
                    return
                delay = min(
                    self.options.max_reconnect_delay,
                    self.options.reconnect_delay * 2 ** min(attempts, 30),
                )
                delay *= random.uniform(0.8, 1.0)
                attempts += 1
                self._emit_safe(WKIMEvent.RECONNECTING, {"attempt": attempts, "delay": delay})
                await asyncio.sleep(delay)
        finally:
            self._result = None
            self._fail_ready(WKIMError(ErrorCode.CLOSED, "Connection stopped"))

    async def _clean_session(self, session: _Session, error: WKIMError) -> None:
        for future in tuple(session.pending.values()):
            if not future.done():
                future.set_exception(error)
        children = [t for t in (session.reader, session.heartbeat) if t is not None]
        for task in children:
            if not task.done():
                task.cancel()
        await asyncio.gather(*children, return_exceptions=True)
        try:
            async with asyncio.timeout(self.options.close_timeout):
                await session.ws.close()
        except Exception:
            session.ws.transport.abort()

    async def _request(
        self,
        session: _Session,
        method: str,
        params: dict[str, Any],
        deadline: float | None = None,
    ) -> Any:
        request_id = str(uuid.uuid4())
        wire = encode({"id": request_id, "method": method, "params": params})
        try:
            size = len(wire.encode("utf-8"))
        except UnicodeError:
            raise WKIMError(ErrorCode.INVALID_ARGUMENT, "Request must be valid UTF-8") from None
        if size > self.options.max_message_bytes:
            raise WKIMError(ErrorCode.INVALID_ARGUMENT, "Request exceeds max_message_bytes")
        if (
            len(session.pending) >= self.options.max_pending_requests
            or session.pending_bytes + size > self.options.max_pending_bytes
        ):
            raise WKIMError(ErrorCode.QUEUE_FULL, "Pending request capacity exceeded")
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        session.pending[request_id] = future
        if method == "connect":
            session.connect_id = request_id
        session.pending_bytes += size
        try:
            async with asyncio.timeout(deadline or self.options.request_timeout):
                await session.ws.send(wire)
                return await future
        except TimeoutError:
            raise WKIMError(
                ErrorCode.TIMEOUT, "Request timed out; outcome may be unknown"
            ) from None
        except WKIMError:
            raise
        except Exception:
            raise WKIMError(
                ErrorCode.CONNECTION_LOST, "Request interrupted by connection loss"
            ) from None
        finally:
            session.pending.pop(request_id, None)
            session.pending_bytes -= size
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def _heartbeat(self, session: _Session) -> None:
        try:
            while True:
                await asyncio.sleep(self.options.ping_interval)
                await self._request(session, "ping", {}, self.options.pong_timeout)
        except WKIMError as error:
            session.failure = error
            session.ws.transport.abort()

    async def _read(self, session: _Session) -> None:
        try:
            async for raw in session.ws:
                frame = decode_frame(raw)
                if "id" in frame:
                    self._response(session, frame)
                elif isinstance(frame.get("method"), str):
                    await self._notification(
                        session, frame, len(raw.encode() if isinstance(raw, str) else raw)
                    )
                else:
                    raise WKIMError(ErrorCode.PROTOCOL, "Invalid JSON-RPC envelope")
        except WKIMError as protocol_error:
            session.failure = protocol_error
            session.terminal = True
            raise
        except ConnectionClosed as closed:
            codes = {frame.code for frame in (closed.sent, closed.rcvd) if frame is not None}
            if codes.intersection({1002, 1003, 1007, 1008, 1009}):
                session.failure = WKIMError(ErrorCode.PROTOCOL, "WebSocket protocol rejected")
                session.terminal = True
                raise session.failure from None
            raise
        finally:
            error = session.failure or WKIMError(ErrorCode.CONNECTION_LOST, "Connection lost")
            for future in tuple(session.pending.values()):
                if not future.done():
                    future.set_exception(error)

    def _response(self, session: _Session, frame: dict[str, Any]) -> None:
        if not isinstance(frame["id"], str):
            raise WKIMError(ErrorCode.PROTOCOL, "Invalid response ID")
        future = session.pending.get(frame["id"])
        if future is None or future.done():
            return  # Late responses are not allowed to complete a newer request.
        if ("result" in frame) == ("error" in frame) or "method" in frame:
            raise WKIMError(ErrorCode.PROTOCOL, "Response must contain result or error")
        if "error" in frame:
            if frame["id"] == session.connect_id:
                session.terminal = True
            error = frame["error"]
            if not isinstance(error, dict) or type(error.get("code")) is not int:
                raise WKIMError(ErrorCode.PROTOCOL, "Invalid error response")
            future.set_exception(WKIMError(error["code"], "Server rejected request"))
        else:
            if frame["id"] == session.connect_id:
                session.auth_response = True
            future.set_result(frame["result"])

    async def _notification(self, session: _Session, frame: dict[str, Any], size: int) -> None:
        method = frame["method"]
        if method not in ("recv", "event", "disconnect"):
            return  # Uncorrelated pong and future extension notifications are harmless.
        params = frame.get("params")
        if not isinstance(params, dict):
            raise WKIMError(ErrorCode.PROTOCOL, "Invalid notification params")
        if method == "disconnect":
            code = params.get("reasonCode", ErrorCode.CLOSED)
            if type(code) is not int:
                code = ErrorCode.CLOSED
            session.terminal = True
            session.failure = WKIMError(code, "Server disconnected client")
            raise session.failure
        if not self.is_connected:
            if not session.auth_response:
                raise WKIMError(ErrorCode.PROTOCOL, "Notification before authentication")
            await session.auth_ready.wait()
        if method == "recv":
            message_identity(params)
            if (
                not isinstance(params.get("header"), dict)
                or "payload" not in params
                or not isinstance(params.get("channelId"), str)
                or type(params.get("channelType")) is not int
                or not isinstance(params.get("fromUid"), str)
                or type(params.get("timestamp")) is not int
            ):
                raise WKIMError(ErrorCode.PROTOCOL, "Invalid received message")
            params["payload"] = decode_payload(params["payload"])
            self._emit(WKIMEvent.MESSAGE, params, size)
            # Queue acceptance is a transport receipt, not application processing or read status.
            ack = {
                "header": params["header"],
                "messageId": params["messageId"],
                "messageSeq": params["messageSeq"],
            }
            async with asyncio.timeout(self.options.request_timeout):
                await session.ws.send(encode({"method": "recvack", "params": ack}))
        else:
            if (
                not isinstance(params.get("id"), str)
                or not params["id"]
                or not isinstance(params.get("type"), str)
                or not params["type"]
                or type(params.get("timestamp")) is not int
                or "data" not in params
            ):
                raise WKIMError(ErrorCode.PROTOCOL, "Invalid custom event")
            if isinstance(params["data"], str):
                try:
                    params["data"] = loads(params["data"])
                except (ValueError, RecursionError):
                    pass
            self._emit(WKIMEvent.CUSTOM_EVENT, params, size)

    def _emit(self, event: WKIMEvent, value: Any, size: int = 256) -> None:
        if not self._listeners[event] or self._destroyed:
            return
        if self._events.full() or self._event_bytes + size > self.options.max_event_bytes:
            raise WKIMError(ErrorCode.QUEUE_FULL, "Event queue capacity exceeded")
        self._event_bytes += size
        self._events.put_nowait((event, value, size))

    def _emit_safe(self, event: WKIMEvent, value: Any) -> None:
        try:
            self._emit(event, value)
        except WKIMError:
            # Never recursively enqueue errors into an overloaded dispatcher.
            pass
        if self.options.debug_logging:
            _logger.debug("SDK lifecycle event: %s", event.value)

    async def _dispatch(self) -> None:
        while not self._destroyed:
            event, value, size = await self._events.get()
            try:
                for callback in tuple(self._listeners[event]):
                    if callback not in self._listeners[event]:
                        continue
                    try:
                        result = callback(value)
                        if inspect.isawaitable(result):
                            await result
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():  # type: ignore[union-attr]
                            raise
                        if event != WKIMEvent.ERROR:
                            self._emit_safe(
                                WKIMEvent.ERROR, WKIMError(ErrorCode.CALLBACK, "Callback cancelled")
                            )
                    except Exception:
                        if event != WKIMEvent.ERROR:
                            self._emit_safe(
                                WKIMEvent.ERROR, WKIMError(ErrorCode.CALLBACK, "Callback failed")
                            )
            finally:
                self._event_bytes -= size
