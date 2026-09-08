"""Explicit group acceptance through installed SDKs and a real three-node cluster."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from cluster import (
    JS_REVISION,
    Cluster,
    JSPeer,
    PythonPeer,
    eventually,
    provenance,
)
from product import request, stop

from wukong_easy_sdk import WKIMChannelType, WKIMError

USERS = ["group-alice", "group-bob", "group-carol", "group-dave"]
MAIN = "python-group-main"
ISOLATED = "python-group-isolated"
SERVER_REVISION = "2a295e0d9881ef5356728a85d56b052c4b0d9c86"


async def mutate(cluster, path, body):
    result = await request(cluster.api(0), path, body)
    assert result["status"] == 200, f"Management failed: {path}"


async def failure_evidence(cluster):
    """Read bounded delivery signals from this fixture only, before destroying it."""

    def collect(index):
        evidence = {"node": index + 1, "process_exit": cluster.processes[index].returncode}
        try:
            with urllib.request.urlopen(cluster.api(index) + "/metrics", timeout=2) as response:
                lines = response.read(2_000_000).decode().splitlines()
            evidence["delivery_metrics"] = [
                line
                for line in lines
                if line.startswith(("wukongim_delivery_", "wukongim_presence_"))
                and "_bucket{" not in line
            ][:300]
        except Exception as error:
            evidence["metrics_error"] = type(error).__name__
        events = []
        for path in sorted((cluster.root / f"node{index + 1}" / "logs").rglob("*.log"))[:6]:
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 262144))
                for line in stream.read(262144).decode(errors="replace").splitlines():
                    if any(
                        event in line
                        for event in (
                            '"event": "internal.app.delivery.plan_incomplete"',
                            '"raftEvent": "leader_change"',
                        )
                    ):
                        try:
                            event = json.loads(line[line.index("{") :])
                            events.append(
                                {
                                    key: event[key]
                                    for key in (
                                        "event",
                                        "result",
                                        "phase",
                                        "mode",
                                        "recipients",
                                        "uid",
                                        "ownerNodeID",
                                        "error",
                                        "raftScope",
                                        "raftEvent",
                                        "nodeID",
                                        "slotID",
                                    )
                                    if key in event
                                }
                            )
                        except (ValueError, KeyError):
                            pass
        evidence["delivery_events"] = events[-20:]
        return evidence

    evidence = {
        "nodes": await asyncio.gather(*(asyncio.to_thread(collect, index) for index in range(3)))
    }
    try:
        evidence["presence"] = await request(cluster.api(0), "/user/onlinestatus", USERS)
    except Exception as error:
        evidence["presence_error"] = type(error).__name__
    return evidence


class Group:
    def __init__(self, peers, report, cluster):
        self.peers = peers
        self.report = report
        self.cluster = cluster
        self.sequences = {}

    async def send(self, phase, sender, recipients, reason=1, channel=MAIN):
        """Assert ACK, all intended recipients and bounded exclusion of every other client."""
        assert all(peer.messages.empty() for peer in self.peers), "Unexpected prior delivery"
        before = [peer.received for peer in self.peers]
        payload = {"counter": len(self.report["phases"]), "type": 1, "content": f"群聊 🌍 {phase}"}
        peer = self.peers[sender]
        ack = None
        try:
            ack = (
                await peer.im.send(channel, WKIMChannelType.GROUP, payload)
                if isinstance(peer, PythonPeer)
                else await peer.send(channel, payload, channel_type=2)
            )
        except WKIMError as error:
            assert reason != 1 and error.code == reason
        else:
            assert ack["reasonCode"] == reason
            assert isinstance(peer, JSPeer) or reason == 1, "Python must raise on rejection"
        if reason == 1:
            assert ack["messageSeq"] > self.sequences.get(channel, 0)
            self.sequences[channel] = ack["messageSeq"]
            for index in recipients:
                try:
                    message = await asyncio.wait_for(self.peers[index].messages.get(), 8)
                except TimeoutError:
                    self.report["missing_delivery"] = {
                        "phase": phase,
                        "recipient": index,
                        "ack": ack,
                        "received_delta": [
                            p.received - n for p, n in zip(self.peers, before, strict=True)
                        ],
                        "duplicates": [p.duplicates for p in self.peers],
                        "errors": [p.errors for p in self.peers],
                        "connect_counts": [len(p.connects) for p in self.peers],
                        "js_wire_frames": dict(self.peers[1].wire_frames),
                        "js_wire_received": list(self.peers[1].wire_received),
                        "server_evidence": await failure_evidence(self.cluster),
                    }
                    raise AssertionError(f"Missing delivery: {phase}, recipient={index}") from None
                assert message["channelType"] == 2 and message["channelId"] == channel
                assert message["fromUid"] == USERS[sender] and message["payload"] == payload
                assert (message["messageId"], message["messageSeq"]) == (
                    ack["messageId"],
                    ack["messageSeq"],
                )
        # Required negative observation, after all expected deliveries (or a denied SEND).
        await asyncio.sleep(1)
        assert all(peer.messages.empty() for peer in self.peers), f"Unexpected delivery: {phase}"
        assert [p.received - n for p, n in zip(self.peers, before, strict=True)] == [
            int(i in recipients) for i in range(4)
        ], f"Duplicate or missing delivery: {phase}"
        for peer in self.peers:
            if isinstance(peer, JSPeer):
                assert not peer.reader.done(), "JS event bridge exited"
        self.report["phases"].append(
            {"phase": phase, "sender": sender, "recipients": recipients, "reason": reason}
        )
        print(f"Group phase passed: {phase}", flush=True)


async def members(cluster, operation, indices):
    await mutate(
        cluster,
        f"/channel/subscriber_{operation}",
        {
            "channel_id": MAIN,
            "channel_type": 2,
            "subscribers": [USERS[i] for i in indices],
        },
    )


async def blacklist(cluster, operation, index):
    await mutate(
        cluster,
        f"/channel/blacklist_{operation}",
        {
            "channel_id": MAIN,
            "channel_type": 2,
            "uids": [USERS[index]],
        },
    )


async def exercise(cluster, peers, report):
    for channel, indices in ((MAIN, [0, 1, 2]), (ISOLATED, [0, 1])):
        await mutate(
            cluster,
            "/channel",
            {
                "channel_id": channel,
                "channel_type": 2,
                "allow_stranger": 0,
                "reset": 1,
                "subscribers": [USERS[i] for i in indices],
            },
        )
    group = Group(peers, report, cluster)
    await group.send("member_fanout", 0, [1, 2])
    await group.send("channel_isolation", 1, [0], channel=ISOLATED)
    await group.send("nonmember_rejected", 3, [], reason=3)
    await members(cluster, "add", [3])
    await group.send("added_member_send", 3, [0, 1, 2])
    await members(cluster, "remove", [1])
    await group.send("removed_js_member_rejected", 1, [], reason=3)
    await group.send("removed_member_excluded", 2, [0, 3])
    await blacklist(cluster, "add", 2)
    await group.send("blacklisted_python_rejected", 2, [], reason=4)
    counts = [len(peer.connects) for peer in peers]
    started = time.monotonic()
    report["cut_connections"] = [len(proxy.writers) // 2 for proxy in cluster.proxies]
    assert report["cut_connections"] == [2, 1, 1]
    for proxy in cluster.proxies:
        proxy.paused = True
        proxy.abort()
    await asyncio.sleep(1)
    for proxy in cluster.proxies:
        proxy.paused = False
    await eventually(
        lambda: all(len(peer.connects) > count for peer, count in zip(peers, counts, strict=True)),
        20,
    )
    assert [p.connects[-1]["nodeId"] for p in peers] == [1, 2, 3, 1]
    report["reconnected_clients"] = 4
    report["recovery_seconds"] = round(time.monotonic() - started, 3)
    await group.send("reconnected_nonmember_rejected", 1, [], reason=3)
    await group.send("reconnected_blacklist_preserved", 2, [], reason=4)
    await blacklist(cluster, "remove", 2)
    await group.send("blacklist_removed_membership_preserved", 2, [0, 3])
    await members(cluster, "add", [1])
    await group.send("readded_js_member_send", 1, [0, 2, 3])
    await blacklist(cluster, "add", 1)
    await group.send("blacklisted_js_rejected", 1, [], reason=4)
    await blacklist(cluster, "remove", 1)
    await group.send("js_blacklist_removed_send", 1, [0, 2, 3])
    report["duplicate_callbacks"] = sum(peer.duplicates for peer in peers)
    assert report["duplicate_callbacks"] == 0


async def example(cluster, peers, token, report):
    """Run the actual interactive CLI with the installed package, including a rejected SEND."""
    await peers[3].im.destroy()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).parents[1] / "examples/group_chat.py"),
        env=dict(
            os.environ,
            WKIM_UID=USERS[3],
            WKIM_TOKEN=token,
            WKIM_GROUP=MAIN,
            WKIM_URL=cluster.url(0),
            WKIM_CA_FILE=str(cluster.ca_file),
        ),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    async def line(prefix):
        value = await asyncio.wait_for(process.stdout.readline(), 15)
        assert value.decode().startswith(prefix), f"Example did not print: {prefix}"

    async def command(value):
        process.stdin.write((value + "\n").encode())
        await process.stdin.drain()

    try:
        await line("Connected to group")
        await command("example outbound 群聊 🌍")
        await line("SENDACK received")
        identity = None
        for peer in peers[:3]:
            message = await asyncio.wait_for(peer.messages.get(), 8)
            assert message["payload"] == {"type": 1, "content": "example outbound 群聊 🌍"}
            assert message["channelId"] == MAIN and message["channelType"] == 2
            assert message["fromUid"] == USERS[3]
            current = (message["messageId"], message["messageSeq"])
            assert identity is None or identity == current
            identity = current
        await peers[0].im.send(MAIN, 2, {"type": 1, "content": "example inbound"})
        await line("Received: {'type': 1, 'content': 'example inbound'}")
        for peer in peers[1:3]:
            message = await asyncio.wait_for(peer.messages.get(), 8)
            assert message["payload"] == {"type": 1, "content": "example inbound"}
        await asyncio.sleep(1)
        assert all(peer.messages.empty() for peer in peers)
        before = [peer.received for peer in peers]
        await members(cluster, "remove", [3])
        await command("must be rejected")
        await line("Send failed (code=3)")
        await asyncio.sleep(1)
        assert [peer.received for peer in peers] == before
        await command("/quit")
        await asyncio.wait_for(process.wait(), 8)
        assert process.returncode == 0
        assert await process.stdout.read() == b"", "Unexpected example callback"
        report["example"] = {
            "send_recipients": 3,
            "received": 1,
            "rejection_code": 3,
            "exit_code": 0,
        }
        print("Group example passed: send, receive, rejection, /quit", flush=True)
    finally:
        await stop(process)
        report["example_process_running"] = process.returncode is None


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--js-entry", type=Path, required=True)
    parser.add_argument("--install-report", type=Path, required=True)
    parser.add_argument("--package-source", choices=["pypi", "wheel"], default="pypi")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = set(asyncio.all_tasks())
    started = time.monotonic()
    report = {
        "status": "failed",
        "started_at": datetime.now(UTC).isoformat(),
        "server_revision": SERVER_REVISION,
        "js_revision": JS_REVISION,
        "python_sdk_version": importlib.metadata.version("wukong-easy-sdk"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "server_sha256": hashlib.sha256(args.server.read_bytes()).hexdigest(),
        "provenance": provenance(args, SERVER_REVISION),
        "phases": [],
        "exclusion_observation_ms": 1000,
    }
    source = Path(__file__).parents[1]
    report["harness_revision"] = (
        await asyncio.to_thread(
            subprocess.check_output,
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            text=True,
            timeout=10,
        )
    ).strip()
    report["harness_worktree_dirty"] = bool(
        (
            await asyncio.to_thread(
                subprocess.check_output,
                ["git", "-C", str(source), "status", "--porcelain", "--", "tests", "examples"],
                text=True,
                timeout=10,
            )
        ).strip()
    )
    report["provenance"]["harness_sha256"].update(
        {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in ("tests/group.py", "examples/group_chat.py")
        }
    )
    with tempfile.TemporaryDirectory(prefix="wkgrp-") as directory:
        cluster = Cluster(Path(directory), args.server.resolve(), log_level="info")
        peers = []
        try:
            async with asyncio.timeout(180):
                await cluster.start()
                for i, uid in enumerate(USERS):
                    token = secrets.token_hex(24)
                    await cluster.token(uid, token)
                    if i == 1:
                        peer = JSPeer()
                        peers.append(peer)
                        await peer.start(cluster, token, args.js_entry.resolve(), uid=uid)
                    else:
                        peer = PythonPeer(cluster, uid, token, i % 3)
                        peers.append(peer)
                        await peer.im.connect()
                report["connected_nodes"] = [p.connects[-1]["nodeId"] for p in peers]
                assert report["connected_nodes"] == [1, 2, 3, 1]
                await exercise(cluster, peers, report)
                await example(cluster, peers, token, report)
                for peer in peers:
                    if isinstance(peer, PythonPeer):
                        await peer.im.destroy()
                    else:
                        await peer.close()
                async with asyncio.timeout(20):
                    while True:
                        statuses = await request(cluster.api(0), "/user/onlinestatus", USERS)
                        if all(item.get("online", 0) == 0 for item in statuses):
                            break
                        await asyncio.sleep(0.05)
                report["offline_confirmed"] = True
                report["matched_group_deliveries"] = sum(
                    len(phase["recipients"]) for phase in report["phases"]
                )
                report["status"] = "passed"
        finally:
            for peer in peers:
                if isinstance(peer, PythonPeer):
                    await peer.im.destroy()
                else:
                    await peer.close()
            await cluster.close()
            await eventually(lambda: set(asyncio.all_tasks()) <= baseline, 10)
            report["cleanup"] = {
                "owned_processes_running": sum(
                    p.returncode is None for p in cluster.processes if p
                ),
                "proxy_connections": sum(len(p.tasks) for p in cluster.proxies),
                "extra_asyncio_tasks": len(set(asyncio.all_tasks()) - baseline),
                "js_processes_running": sum(
                    p.process.returncode is None
                    for p in peers
                    if isinstance(p, JSPeer) and p.process
                ),
            }
            assert not any(report["cleanup"].values()), "Owned resources remain"
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
            args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
