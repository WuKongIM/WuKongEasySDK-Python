"""Explicit black-box acceptance against an isolated, Token-authenticated real product process."""

import argparse
import asyncio
import json
import os
import secrets
import socket
import tempfile
import time
import urllib.request
from pathlib import Path

from wukong_easy_sdk import WKIM, AuthOptions, WKIMError, WKIMEvent


def free_ports(count: int) -> list[int]:
    sockets = [socket.socket() for _ in range(count)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def http(base: str, path: str, data=None):
    req = urllib.request.Request(
        base + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=2) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


async def request(base, path, data=None):
    return await asyncio.to_thread(http, base, path, data)


async def stop(process):
    if process is None or process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 8)
    except TimeoutError:
        process.kill()
        await process.wait()


async def offline(base):
    async with asyncio.timeout(10):
        while True:
            statuses = await request(base, "/user/onlinestatus", ["python-alice", "python-bob"])
            if all(item.get("online", 0) == 0 for item in statuses):
                return
            await asyncio.sleep(0.05)


async def python_peers(url, alice_token, bob_token):
    alice = WKIM(url, AuthOptions("python-alice", alice_token))
    bob = WKIM(url, AuthOptions("python-bob", bob_token))
    alice_in, bob_in = asyncio.Queue(), asyncio.Queue()
    alice.on(WKIMEvent.MESSAGE, alice_in.put_nowait)
    bob.on(WKIMEvent.MESSAGE, bob_in.put_nowait)
    async with alice, bob:
        for sender, target, incoming, text in [
            (alice, "python-bob", bob_in, "你好 from Python Alice 🌍"),
            (bob, "python-alice", alice_in, "你好 from Python Bob 🌍"),
        ]:
            payload = {"type": 1, "content": text}
            ack = await sender.send(target, 1, payload)
            message = await asyncio.wait_for(incoming.get(), 5)
            assert ack["reasonCode"] == 1
            assert ack["messageId"] == message["messageId"]
            assert ack["messageSeq"] == message["messageSeq"]
            assert message["payload"] == payload
        await alice.ping()
        await bob.ping()
        await alice.disconnect()
        await alice.connect()
        await bob.send("python-alice", 1, {"type": 1, "content": "after reconnect"})
        assert (await asyncio.wait_for(alice_in.get(), 5))["payload"][
            "content"
        ] == "after reconnect"
    bad = WKIM(url, AuthOptions("python-alice", "intentionally-invalid-token"))
    try:
        await bad.connect()
    except WKIMError as error:
        assert error.code == 2
    else:
        raise AssertionError("Invalid Token was accepted")
    finally:
        await bad.destroy()


async def js_interop(url, alice_token, bob_token, js_entry):
    env = dict(os.environ, WKIM_URL=url, WKIM_BOB_TOKEN=bob_token, WKIM_JS_ENTRY=js_entry)
    peer = await asyncio.create_subprocess_exec(
        "node",
        str(Path(__file__).with_name("js_peer.cjs")),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        assert await asyncio.wait_for(peer.stdout.readline(), 10) == b"READY\n"
        im = WKIM(url, AuthOptions("python-alice", alice_token))
        incoming = asyncio.Queue()
        im.on(WKIMEvent.MESSAGE, incoming.put_nowait)
        async with im:
            for payload in [
                {"type": 1, "content": "Python ↔ JS 中文 🌍"},
                {"type": 1, "content": "x" * 2000},
            ]:
                ack = await im.send("python-bob", 1, payload)
                assert ack["reasonCode"] == 1
                message = await asyncio.wait_for(incoming.get(), 5)
                assert message["fromUid"] == "python-bob"
                assert message["payload"] == payload
    finally:
        await stop(peer)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--js-entry", help="Built JS 2.0.4 dist/cjs/index.js")
    args = parser.parse_args()
    cluster, api, gateway, manager = free_ports(4)
    base = f"http://127.0.0.1:{api}"
    url = f"ws://127.0.0.1:{gateway}/ws"
    alice_token, bob_token = secrets.token_hex(24), secrets.token_hex(24)
    with tempfile.TemporaryDirectory(prefix="wkim-python-product-") as directory:
        root = Path(directory)
        config = root / "wukongim.toml"
        config.write_text(f'''[node]
id = 1
data_dir = "{root / "data"}"
[cluster]
id = "python-sdk-test"
listen_addr = "127.0.0.1:{cluster}"
nodes = [{{id=1,addr="127.0.0.1:{cluster}"}}]
initial_slot_count = 8
hash_slot_count = 256
slot_replica_n = 1
[api]
listen_addr = "127.0.0.1:{api}"
[manager]
listen_addr = "127.0.0.1:{manager}"
[gateway]
token_auth_on = true
[[gateway.listeners]]
name = "ws"
network = "websocket"
address = "127.0.0.1:{gateway}"
transport = "gnet"
protocol = "wsmux"
path = "/ws"
[log]
level = "error"
console = false
dir = "{root / "logs"}"
''')
        process = None
        with (root / "server.log").open("wb") as output:
            try:
                process = await asyncio.create_subprocess_exec(
                    str(Path(args.server).resolve()),
                    "-config",
                    str(config),
                    cwd=root,
                    env={k: v for k, v in os.environ.items() if not k.startswith("WK_")},
                    stdout=output,
                    stderr=output,
                )
                start = time.monotonic()
                async with asyncio.timeout(40):
                    while True:
                        if process.returncode is not None:
                            raise RuntimeError("Product exited before readiness")
                        try:
                            await request(base, "/readyz")
                            break
                        except OSError:
                            await asyncio.sleep(0.1)
                for uid, token in [("python-alice", alice_token), ("python-bob", bob_token)]:
                    await request(
                        base,
                        "/user/token",
                        {
                            "uid": uid,
                            "token": token,
                            "device_flag": 2,
                            "device_level": 1,
                        },
                    )
                async with asyncio.timeout(40):
                    await python_peers(url, alice_token, bob_token)
                    await offline(base)
                    print("PASS Python/Python: messaging, ping, reconnect, bad Token, cleanup")
                    if args.js_entry:
                        await js_interop(
                            url, alice_token, bob_token, str(Path(args.js_entry).resolve())
                        )
                        await offline(base)
                        print("PASS Python/JS 2.0.4: bidirectional Unicode, 2 KB payloads, cleanup")
                print(f"PASS product: auth ON, 256 hash slots, {time.monotonic() - start:.2f}s")
            finally:
                await stop(process)


if __name__ == "__main__":
    asyncio.run(main())
