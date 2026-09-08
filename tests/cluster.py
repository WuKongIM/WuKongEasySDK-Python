"""Explicit bounded acceptance through real three-node processes and opaque TLS proxies."""

import argparse
import asyncio
import contextlib
import hashlib
import importlib.metadata
import json
import os
import platform
import secrets
import ssl
import subprocess
import tempfile
import time
from collections import Counter, deque
from pathlib import Path

import psutil
import trustme
from product import free_ports, request, stop

from wukong_easy_sdk import WKIM, AuthOptions, ErrorCode, WKIMError, WKIMEvent, WKIMOptions

SERVER_REVISION = "e7ef61ba702e045648b9fa535f051e5b2ee4a1db"
JS_REVISION = "9c03c98c725982fac224cd1d3b52456eae983975"


def provenance(args, server_revision=SERVER_REVISION):
    """Fail closed on mismatched source stamps or editable SDK installations."""

    def command(*argv):
        return subprocess.check_output(argv, text=True, timeout=15).strip()

    build = command("go", "version", "-m", str(args.server))
    assert f"vcs.revision={server_revision}" in build, "Server source revision mismatch"
    assert "vcs.modified=false" in build, "Server must come from a clean checkout"
    js_root = args.js_entry.resolve().parents[2]
    assert command("git", "-C", str(js_root), "rev-parse", "HEAD") == JS_REVISION
    assert not command("git", "-C", str(js_root), "status", "--porcelain")
    package = importlib.metadata.distribution("wukong-easy-sdk")
    direct = json.loads(package.read_text("direct_url.json") or "{}")
    assert not direct.get("dir_info"), "Use an independently installed distribution"
    install = json.loads(args.install_report.read_text())
    records = [item for item in install["install"] if item["metadata"]["name"] == "wukong-easy-sdk"]
    assert len(records) == 1 and records[0]["metadata"]["version"] == package.version
    archive = records[0]["download_info"]
    digest = archive["archive_info"]["hashes"]["sha256"]
    if args.package_source == "pypi":
        assert archive["url"].startswith("https://files.pythonhosted.org/")
        assert package.version == "0.1.0"
        assert digest == "d653a73537aa0ca66aa21eb4a6ab2f60bfc5b819e018f233a8a9c9502671cf48"
    return {
        "package_source": args.package_source,
        "wheel_sha256": digest,
        "websockets": importlib.metadata.version("websockets"),
        "node": command("node", "--version"),
        "harness_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("cluster.py", "cluster_peer.cjs", "product.py")
        },
    }


async def eventually(predicate, seconds=30):
    # Public state and owned process/proxy state have no common event primitive.
    async with asyncio.timeout(seconds):
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.05)


class Proxy:
    """Terminate TLS and forward bytes; fault controls never synthesize SDK frames."""

    def __init__(self, upstream):
        self.upstream = upstream
        self.paused = False
        self.withhold = False
        self.writers = set()
        self.tasks = set()
        self.server = None

    async def handle(self, reader, writer):
        current = asyncio.current_task()
        self.tasks.add(current)
        self.writers.add(writer)
        other = None
        pumps = []
        try:
            if self.paused:
                return
            remote, other = await asyncio.open_connection("127.0.0.1", self.upstream)
            self.writers.add(other)

            async def pump(source, target, downstream=False):
                while data := await source.read(65536):
                    if downstream and self.withhold:
                        continue
                    target.write(data)
                    await target.drain()

            pumps = [
                asyncio.create_task(pump(reader, other)),
                asyncio.create_task(pump(remote, writer, True)),
            ]
            done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (OSError, ConnectionError):
            pass
        finally:
            for task in pumps:
                task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            for stream in (writer, other):
                if stream:
                    stream.transport.abort()
                    self.writers.discard(stream)
            self.tasks.discard(current)

    def abort(self):
        assert self.writers, "Fault injection needs an active connection"
        for writer in list(self.writers):
            writer.transport.abort()

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in list(self.writers):
            writer.transport.abort()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class Cluster:
    """Own exactly three processes, their isolated files, and loopback listeners."""

    def __init__(self, root, binary):
        self.root = root
        self.binary = binary
        ports = free_ports(15)
        self.ports = [ports[i : i + 5] for i in range(0, 15, 5)]
        self.processes = [None] * 3
        self.logs = []
        self.proxies = []
        ca = trustme.CA()
        self.ca_file = root / "ca.pem"
        ca.cert_pem.write_to_path(self.ca_file)
        certificate = ca.issue_cert("localhost", "127.0.0.1")
        self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.tls.minimum_version = ssl.TLSVersion.TLSv1_2
        certificate.configure_cert(self.tls)

    def api(self, index):
        return f"http://127.0.0.1:{self.ports[index][1]}"

    def url(self, index):
        return f"wss://127.0.0.1:{self.ports[index][4]}/ws"

    async def start(self):
        nodes = ",".join(
            f'{{id={i + 1},addr="127.0.0.1:{p[0]}"}}' for i, p in enumerate(self.ports)
        )
        for i, (cluster, api, gateway, manager, tls) in enumerate(self.ports):
            node = self.root / f"node{i + 1}"
            node.mkdir()
            (node / "wukongim.toml").write_text(f'''[node]
id = {i + 1}
data_dir = "{node / "data"}"
[cluster]
id = "python-three-node-acceptance"
listen_addr = "127.0.0.1:{cluster}"
nodes = [{nodes}]
hash_slot_count = 256
initial_slot_count = 12
slot_replica_n = 3
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
[delivery]
enable = true
[plugin]
socket_path = "{self.root / f"n{i + 1}.sock"}"
[observability]
metrics_enable = true
[log]
level = "error"
console = false
dir = "{node / "logs"}"
''')
            await self.spawn(i)
            proxy = Proxy(gateway)
            proxy.server = await asyncio.start_server(proxy.handle, "127.0.0.1", tls, ssl=self.tls)
            self.proxies.append(proxy)
        await asyncio.gather(*(self.ready(i) for i in range(3)))

    async def spawn(self, index):
        node = self.root / f"node{index + 1}"
        output = (node / "process.log").open("ab")
        self.logs.append(output)
        self.processes[index] = await asyncio.create_subprocess_exec(
            str(self.binary),
            "-config",
            str(node / "wukongim.toml"),
            cwd=node,
            env={k: v for k, v in os.environ.items() if not k.startswith("WK_")},
            stdout=output,
            stderr=output,
        )

    async def ready(self, index):
        async with asyncio.timeout(60):
            while True:
                assert self.processes[index].returncode is None, "Product exited before readiness"
                try:
                    await request(self.api(index), "/readyz")
                    return
                except OSError:
                    await asyncio.sleep(0.1)

    async def token(self, uid, token, index=0):
        await request(
            self.api(index),
            "/user/token",
            {
                "uid": uid,
                "token": token,
                "device_flag": 2,
                "device_level": 1,
            },
        )

    async def close(self):
        await asyncio.gather(*(proxy.close() for proxy in self.proxies))
        await asyncio.gather(*(stop(process) for process in self.processes))
        for output in self.logs:
            output.close()


class Inbox:
    """Bounded application deduplication; raw duplicate deliveries stay observable."""

    def __init__(self):
        self.messages = asyncio.Queue(maxsize=128)
        self.recent = deque()
        self.ids = set()
        self.received = 0
        self.duplicates = 0

    def receive(self, message):
        self.received += 1
        identity = message["messageId"]
        if identity in self.ids:
            self.duplicates += 1
            return
        if len(self.recent) == 8192:
            self.ids.remove(self.recent.popleft())
        self.recent.append(identity)
        self.ids.add(identity)
        self.messages.put_nowait(message)


class PythonPeer(Inbox):
    def __init__(self, cluster, uid, token, index):
        super().__init__()
        self.uid = uid
        self.im = WKIM(
            cluster.url(index),
            AuthOptions(uid, token),
            WKIMOptions(
                ca_file=str(cluster.ca_file),
                ping_interval=5,
                pong_timeout=3,
                connect_timeout=3,
                request_timeout=8,
                reconnect_delay=0.5,
                max_reconnect_delay=2,
                max_reconnect_attempts=20,
            ),
        )
        self.connects = deque(maxlen=128)
        self.errors = Counter()
        self.im.on(WKIMEvent.MESSAGE, self.receive)
        self.im.on(WKIMEvent.CONNECT, self.connects.append)
        self.im.on(WKIMEvent.ERROR, lambda error: self.errors.update([error.code]))


class JSPeer(Inbox):
    def __init__(self):
        super().__init__()
        self.process = None
        self.reader = None
        self.acks = asyncio.Queue(maxsize=128)
        self.connects = deque(maxlen=128)
        self.errors = 0
        self.ready = False
        self.wire_frames = Counter()
        self.wire_received = deque(maxlen=128)

    async def start(self, cluster, token, entry, uid="cluster-bob"):
        self.process = await asyncio.create_subprocess_exec(
            "node",
            str(Path(__file__).with_name("cluster_peer.cjs")),
            env=dict(
                os.environ,
                WKIM_URL=cluster.url(1),
                WKIM_BOB_TOKEN=token,
                WKIM_UID=uid,
                WKIM_JS_ENTRY=str(entry),
                NODE_EXTRA_CA_CERTS=str(cluster.ca_file),
            ),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self.reader = asyncio.create_task(self.read())
        await eventually(lambda: self.ready or self.reader.done(), 15)
        if self.reader.done():
            self.reader.result()
        assert self.ready, "JS peer did not connect"

    async def read(self):
        while line := await self.process.stdout.readline():
            item = json.loads(line)
            kind = item["kind"]
            if kind == "message":
                self.receive(item["message"])
            elif kind == "wire":
                self.wire_frames.update([item["frame"]])
                if item.get("messageId"):
                    self.wire_received.append(item["messageId"])
            elif kind in ("ack", "failed"):
                self.acks.put_nowait(item)
            elif kind == "connect":
                self.connects.append(item["result"])
            elif kind == "error":
                self.errors += 1
            elif kind == "ready":
                self.ready = True
            else:
                raise AssertionError(f"JS peer failure: {kind}")

    async def send(self, uid, payload, channel_type=1):
        command = {
            "kind": "send",
            "id": payload["counter"],
            "uid": uid,
            "payload": payload,
            "channelType": channel_type,
        }
        self.process.stdin.write(json.dumps(command).encode() + b"\n")
        await self.process.stdin.drain()
        result = await asyncio.wait_for(self.acks.get(), 10)
        assert result["id"] == command["id"]
        if result["kind"] == "failed":
            raise WKIMError(result["code"], "JS send rejected")
        return result["ack"]

    async def close(self):
        await stop(self.process)
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)


async def exchange(sender, uid, receiver, counter):
    payload = {"counter": counter, "type": 1, "content": "跨节点 Python / JS 🌍 " + "x" * 2000}
    ack = (
        await sender.send(uid, 1, payload)
        if isinstance(sender, WKIM)
        else await sender.send(uid, payload)
    )
    message = await asyncio.wait_for(receiver.messages.get(), 10)
    assert ack["reasonCode"] == 1
    assert (ack["messageId"], ack["messageSeq"]) == (message["messageId"], message["messageSeq"])
    assert message["payload"] == payload
    return ack


async def transport_fault(cluster, alice, carol, counter):
    """Prove a delivered SEND with an unavailable ACK is not replayed on reconnect."""
    proxy = cluster.proxies[0]
    connections = len(alice.connects)
    before = carol.received
    proxy.withhold = True
    payload = {"counter": counter, "type": 1, "content": "ACK withheld at TLS boundary"}
    pending = asyncio.create_task(alice.im.send("cluster-carol", 1, payload))
    try:
        message = await asyncio.wait_for(carol.messages.get(), 5)
        assert message["payload"] == payload
        assert not pending.done(), "Proxy did not withhold the SENDACK"
        started = time.monotonic()
        proxy.paused = True
        proxy.abort()
        try:
            await asyncio.wait_for(pending, 3)
        except WKIMError as error:
            assert error.code == ErrorCode.CONNECTION_LOST
        else:
            raise AssertionError("SEND must fail when the acknowledged outcome is unavailable")
        await asyncio.sleep(1)
        proxy.withhold = False
        proxy.paused = False
        await eventually(lambda: len(alice.connects) > connections and alice.im.is_connected)
        await alice.im.ping()
        # Observe well beyond reconnect; never retry the ambiguous SEND in the application.
        await asyncio.sleep(1)
        assert carol.received == before + 1, "Ambiguous SEND was replayed or redelivered"
        return {
            "kind": "withheld_ack_and_transport_cut",
            "recovery_seconds": round(time.monotonic() - started, 3),
            "send_error": int(ErrorCode.CONNECTION_LOST),
            "receiver_deliveries": carol.received - before,
        }
    finally:
        proxy.withhold = proxy.paused = False
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


async def restart_fault(cluster, alice):
    """Crash only this harness's ingress process; restart its same durable directory."""
    connections = len(alice.connects)
    started = time.monotonic()
    cluster.processes[0].kill()
    await cluster.processes[0].wait()
    await eventually(lambda: not alice.im.is_connected, 10)
    await asyncio.sleep(1)
    await cluster.spawn(0)
    await cluster.ready(0)
    await eventually(lambda: len(alice.connects) > connections and alice.im.is_connected, 45)
    await alice.im.ping()
    return {
        "kind": "ingress_node_crash_restart",
        "node_id": 1,
        "recovery_seconds": round(time.monotonic() - started, 3),
    }


async def rotate_token(cluster):
    """The backend rotates credentials; applications construct clients with the new Token."""
    uid = "cluster-token-probe"
    old, new = secrets.token_hex(24), secrets.token_hex(24)
    await cluster.token(uid, old, 0)
    first = PythonPeer(cluster, uid, old, 2)
    try:
        await first.im.connect()
    finally:
        await first.im.destroy()
    await cluster.token(uid, new, 1)
    rejected = []
    for index in range(3):
        stale = PythonPeer(cluster, uid, old, index)
        fresh = PythonPeer(cluster, uid, new, index)
        try:
            try:
                await stale.im.connect()
            except WKIMError as error:
                assert error.code == 2
                rejected.append(index + 1)
            else:
                raise AssertionError("Rotated Token remained valid")
            result = await fresh.im.connect()
            assert result["nodeId"] == index + 1
            await fresh.im.ping()
        finally:
            await stale.im.destroy()
            await fresh.im.destroy()
    return {
        "kind": "backend_token_rotation",
        "old_token_rejected_nodes": rejected,
        "new_token_accepted_nodes": [1, 2, 3],
    }


def resources(cluster, js, elapsed):
    def process_sample(pid):
        process = psutil.Process(pid)
        return {"rss_bytes": process.memory_info().rss, "fds": process.num_fds()}

    return {
        "seconds": round(elapsed, 3),
        "python_harness": process_sample(os.getpid()),
        "js_peer": process_sample(js.process.pid),
        "servers": [process_sample(p.pid) for p in cluster.processes],
        "asyncio_tasks": len(asyncio.all_tasks()),
        "proxy_connections": [len(p.tasks) for p in cluster.proxies],
    }


async def assert_offline(cluster):
    async with asyncio.timeout(20):
        while True:
            values = await request(
                cluster.api(1),
                "/user/onlinestatus",
                [
                    "cluster-alice",
                    "cluster-bob",
                    "cluster-carol",
                    "cluster-token-probe",
                ],
            )
            if all(item.get("online", 0) == 0 for item in values):
                return
            await asyncio.sleep(0.1)


async def exercise(cluster, alice, carol, js, args, report):
    counter = 0

    async def roundtrip():
        nonlocal counter
        for sender, uid, receiver in [
            (alice.im, "cluster-bob", js),
            (js, "cluster-alice", alice),
            (alice.im, "cluster-carol", carol),
            (carol.im, "cluster-alice", alice),
        ]:
            counter += 1
            await exchange(sender, uid, receiver, counter)
            report["acknowledged_and_received"] += 1
        assert not js.reader.done(), "JS observation task exited"
        assert not any(p.errors.get(int(ErrorCode.CALLBACK)) for p in (alice, carol))

    await roundtrip()
    print("PASS three-node private-CA WSS: Python/JS and Python/Python", flush=True)
    counter += 1
    report["faults"].append(await transport_fault(cluster, alice, carol, counter))
    await roundtrip()
    print("PASS withheld ACK: CONNECTION_LOST, automatic reconnect, no SEND replay", flush=True)
    report["faults"].append(await restart_fault(cluster, alice))
    await roundtrip()
    print(
        "PASS ingress node crash/restart: automatic WSS recovery and message delivery", flush=True
    )
    report["faults"].append(await rotate_token(cluster))
    await roundtrip()
    print("PASS Token rotation: old Token rejected and new Token accepted on all nodes", flush=True)
    # The first sample follows the fault suite; bounded dedup windows continue filling.
    started = time.monotonic()
    next_sample = 0
    next_fault = 300
    while time.monotonic() - started < args.duration:
        tick = time.monotonic()
        await roundtrip()
        elapsed = time.monotonic() - started
        if elapsed >= next_sample:
            report["samples"].append(resources(cluster, js, elapsed))
            next_sample += 30
            report["workload_seconds"] = round(elapsed, 3)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
            print(
                f"RUN {elapsed:.0f}/{args.duration}s: {report['acknowledged_and_received']} "
                f"ACK/RECV matched; tasks={report['samples'][-1]['asyncio_tasks']}; "
                f"connections={report['samples'][-1]['proxy_connections']}",
                flush=True,
            )
        if elapsed >= next_fault:
            counter += 1
            report["faults"].append(await transport_fault(cluster, alice, carol, counter))
            await roundtrip()
            next_fault += 300
            print("PASS periodic transport interruption", flush=True)
        await asyncio.sleep(max(0, 0.2 - (time.monotonic() - tick)))
    elapsed = time.monotonic() - started
    report["workload_seconds"] = round(elapsed, 3)
    report["samples"].append(resources(cluster, js, elapsed))
    report["deliveries"] = {
        p.uid: {"observed": p.received, "duplicates": p.duplicates} for p in (alice, carol)
    }
    report["deliveries"]["cluster-bob"] = {"observed": js.received, "duplicates": js.duplicates}
    assert all(p.messages.empty() for p in (alice, carol, js)), "Unexpected queued delivery"
    report["errors"] = {p.uid: dict(p.errors) for p in (alice, carol)}
    report["errors"]["js"] = js.errors
    samples = report["samples"]
    # These are acceptance guardrails for this bounded harness, not production memory budgets.
    for name in ("python_harness", "js_peer"):
        assert samples[-1][name]["rss_bytes"] <= samples[0][name]["rss_bytes"] + 32 * 1024**2
        assert samples[-1][name]["fds"] <= samples[0][name]["fds"] + 8
    assert samples[-1]["asyncio_tasks"] <= samples[0]["asyncio_tasks"] + 4
    assert all(sample["proxy_connections"] == [1, 1, 1] for sample in samples)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--js-entry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--install-report", type=Path, required=True, help="pip --report JSON")
    parser.add_argument("--package-source", choices=("pypi", "wheel"), default="pypi")
    parser.add_argument("--duration", type=int, default=60, help="Workload seconds, 0 through 3600")
    args = parser.parse_args()
    if not 0 <= args.duration <= 3600:
        parser.error("duration must be 0 through 3600 seconds")
    task_baseline = set(asyncio.all_tasks())
    started = time.monotonic()
    report = {
        "status": "failed",
        "server_revision": SERVER_REVISION,
        "js_revision": JS_REVISION,
        "python_sdk_version": importlib.metadata.version("wukong-easy-sdk"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "server_sha256": hashlib.sha256(args.server.read_bytes()).hexdigest(),
        "requested_workload_seconds": args.duration,
        "faults": [],
        "samples": [],
        "acknowledged_and_received": 0,
        "provenance": provenance(args),
    }
    with tempfile.TemporaryDirectory(prefix="wkpy-") as directory:
        cluster = Cluster(Path(directory), args.server.resolve())
        peers = []
        js = JSPeer()
        try:
            await cluster.start()
            for uid in ("cluster-alice", "cluster-bob", "cluster-carol"):
                token = secrets.token_hex(24)
                await cluster.token(uid, token)
                if uid == "cluster-bob":
                    await js.start(cluster, token, args.js_entry.resolve())
                else:
                    peer = PythonPeer(cluster, uid, token, 0 if uid == "cluster-alice" else 2)
                    peers.append(peer)
                    await peer.im.connect()
            alice, carol = peers
            report["connected_nodes"] = [
                alice.connects[-1]["nodeId"],
                js.connects[-1]["nodeId"],
                carol.connects[-1]["nodeId"],
            ]
            assert report["connected_nodes"] == [1, 2, 3]
            async with asyncio.timeout(args.duration + 180):
                await exercise(cluster, alice, carol, js, args, report)
            await asyncio.gather(*(peer.im.destroy() for peer in peers))
            await js.close()
            await assert_offline(cluster)
            report["offline_confirmed"] = True
            report["status"] = "passed"
        finally:
            await asyncio.gather(*(peer.im.destroy() for peer in peers))
            await js.close()
            await cluster.close()
            await eventually(lambda: set(asyncio.all_tasks()) <= task_baseline, 10)
            report["cleanup"] = {
                "owned_processes_running": sum(
                    p.returncode is None for p in cluster.processes if p
                ),
                "proxy_connections": sum(len(p.tasks) for p in cluster.proxies),
                "extra_asyncio_tasks": len(set(asyncio.all_tasks()) - task_baseline),
            }
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
            args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
