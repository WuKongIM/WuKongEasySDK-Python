"""Two-terminal chat. Credentials are supplied by a trusted backend via environment."""

import asyncio
import os
import sys
import threading

from wukong_easy_sdk import WKIM, AuthOptions, WKIMChannelType, WKIMError, WKIMEvent, WKIMOptions


async def main() -> None:
    lines: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
    loop = asyncio.get_running_loop()

    def enqueue(line: str) -> None:
        try:
            lines.put_nowait(line)
        except asyncio.QueueFull:
            print("Input queue full; try again")

    def read_input() -> None:
        # A daemon avoids waiting forever on a blocked terminal read during shutdown.
        try:
            for line in sys.stdin:
                loop.call_soon_threadsafe(enqueue, line.rstrip("\r\n"))
            loop.call_soon_threadsafe(enqueue, "/quit")
        except RuntimeError:
            pass  # The event loop has already closed.

    uid, peer = os.environ["WKIM_UID"], os.environ["WKIM_PEER"]
    im = WKIM(
        os.environ.get("WKIM_URL", "ws://127.0.0.1:5200"),
        AuthOptions(uid, os.environ["WKIM_TOKEN"]),
        WKIMOptions(ca_file=os.environ.get("WKIM_CA_FILE")),
    )
    im.on(WKIMEvent.MESSAGE, lambda message: print(f"Received: {message['payload']}"))
    im.on(WKIMEvent.ERROR, lambda _: print("EasySDK operation failed"))
    im.on(WKIMEvent.RECONNECTING, lambda _: print("Reconnecting"))
    async with im:
        print("Connected. Both peers must be online. Type /quit to exit.", flush=True)
        threading.Thread(target=read_input, daemon=True).start()
        while (line := await lines.get()) != "/quit":
            if not line:
                continue
            try:
                await im.send(peer, WKIMChannelType.PERSON, {"type": 1, "content": line})
                print("SENDACK received", flush=True)
            except WKIMError:
                print("Send failed; verify its outcome before retrying")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except (KeyError, WKIMError, ValueError):
        sys.exit("Set WKIM_UID, WKIM_TOKEN, WKIM_PEER and a reachable WKIM_URL")
