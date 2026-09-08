"""Online group chat; a trusted backend supplies credentials and manages membership."""

import asyncio
import concurrent.futures
import os
import sys
import threading

from wukong_easy_sdk import WKIM, AuthOptions, WKIMChannelType, WKIMError, WKIMEvent, WKIMOptions


async def main() -> None:
    uid, group = os.environ["WKIM_UID"], os.environ["WKIM_GROUP"]
    lines: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
    loop = asyncio.get_running_loop()

    def read_input() -> None:
        # Backpressure bounds pending input; a daemon never holds process shutdown.
        try:
            for line in sys.stdin:
                value = line.rstrip("\r\n")
                asyncio.run_coroutine_threadsafe(lines.put(value), loop).result()
                if value == "/quit":
                    return
            asyncio.run_coroutine_threadsafe(lines.put("/quit"), loop).result()
        except (RuntimeError, concurrent.futures.CancelledError):
            pass  # The loop is closing.

    im = WKIM(
        os.environ.get("WKIM_URL", "ws://127.0.0.1:5200"),
        AuthOptions(uid, os.environ["WKIM_TOKEN"]),
        WKIMOptions(ca_file=os.environ.get("WKIM_CA_FILE")),
    )
    im.on(WKIMEvent.MESSAGE, lambda message: print(f"Received: {message['payload']}", flush=True))
    im.on(WKIMEvent.ERROR, lambda _: print("EasySDK operation failed", flush=True))
    im.on(WKIMEvent.RECONNECTING, lambda _: print("Reconnecting", flush=True))
    async with im:
        print("Connected to group. Members must be online. Type /quit to exit.", flush=True)
        threading.Thread(target=read_input, daemon=True).start()
        while (line := await lines.get()) != "/quit":
            if not line:
                continue
            try:
                await im.send(group, WKIMChannelType.GROUP, {"type": 1, "content": line})
                print("SENDACK received", flush=True)
            except WKIMError as error:
                print(
                    f"Send failed (code={error.code}); "
                    "verify membership and outcome before retrying",
                    flush=True,
                )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except (KeyError, WKIMError, ValueError):
        sys.exit("Set WKIM_UID, WKIM_TOKEN, WKIM_GROUP and a reachable WKIM_URL")
