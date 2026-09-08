# Three-node WSS acceptance

Completed runs and raw JSON receipts are in [CLUSTER_VALIDATION.md](CLUSTER_VALIDATION.md).

Approved test seams: the installed SDK's public methods and events, the real JS
SDK, Product HTTP readiness/Token/presence/metrics, and owned process/network
boundaries. No SDK internals or synthetic messaging server are assertion surfaces.

The local plan uses three product processes, 256 hash slots, 12 physical Slots,
three replicas and Token authentication. A private-CA TLS proxy forwards opaque
bytes to each real WSMux listener. The Python and JS clients verify certificates.
All identities, data, certificates, ports and processes belong to this run.

Acceptance proceeds through cross-node messaging, withheld acknowledgments and
transport recovery, a node crash/restart, Token rotation, then a bounded 30-minute
workload with repeated interruptions. It records message identity/sequence,
duplicate observations, recovery times, RSS, descriptors, asyncio tasks and live
proxy connections. A short smoke run is separate from a completed long run.

The test does not claim exactly-once delivery, offline history synchronization,
automatic Token refresh, Internet-wide TLS compatibility or production capacity.
SEND without an acknowledgment has an unknown outcome; the SDK must not replay
it automatically. Applications reconcile history and deduplicate message IDs.

Frozen product source: `e7ef61ba702e045648b9fa535f051e5b2ee4a1db`.
Frozen JS source: `9c03c98c725982fac224cd1d3b52456eae983975` (2.0.4).
Product instructions at that source:

| File | SHA-256 |
| --- | --- |
| `AGENTS.md` | `de01b8e88d03a98ce4c4f20e09c2952c54b5bceefac7f942b6171f4bc99b7c41` |
| `docs-site/FLOW.md` | `7e3df1b0acb670bbe0267b0f5d2e540249c30a1426616f668885e466778f03e4` |

The Python SDK repository has no applicable AGENTS, FLOW, CONTEXT or ADR files.

## Reproduce on Linux or macOS

Use Go 1.25.11, Node 24.3.0 and Python 3.11+ on a host with enough memory for
three product processes. Build from clean source clones outside other Git
repositories: Go 1.25 may stamp the enclosing repository when building a nested
worktree. The harness rejects an incorrect or dirty product stamp. Development
and documentation changes still use task worktrees.

```sh
git clone https://github.com/WuKongIM/WuKongIM.git product
git -C product checkout --detach e7ef61ba702e045648b9fa535f051e5b2ee4a1db
GOWORK=off go -C product build -o /tmp/wukongim-python-cluster ./cmd/wukongim

git clone https://github.com/WuKongIM/WuKongEasySDK-JS.git js
git -C js checkout --detach 9c03c98c725982fac224cd1d3b52456eae983975
npm --prefix js ci --no-audit --no-fund
npm --prefix js run build

git clone https://github.com/WuKongIM/WuKongEasySDK-Python.git python-sdk-harness
git -C python-sdk-harness checkout --detach 1bda54d04154d246be04c8c5452586d77a932333

python3 -m venv /tmp/python-sdk-consumer
/tmp/python-sdk-consumer/bin/python -m pip install --no-cache-dir \
  --index-url https://pypi.org/simple --report /tmp/python-sdk-install.json \
  wukong-easy-sdk==0.1.0 trustme==1.2.1 psutil==7.2.2

# The acceptance harness is newer than the v0.1.0 example tag.
# Run from this pinned checkout. Do not install it editable.
cd python-sdk-harness
/tmp/python-sdk-consumer/bin/python tests/cluster.py \
  --server /tmp/wukongim-python-cluster \
  --js-entry /absolute/path/to/js/dist/cjs/index.js \
  --install-report /tmp/python-sdk-install.json --package-source pypi \
  --duration 1800 --output /tmp/python-sdk-cluster-report.json
```

Use `--duration 60` for smoke or `3600` for a 60-minute run. Duration counts the
workload after startup and the initial fault suite. Failure exits nonzero;
cleanup stops only owned subprocesses, closes proxies and checks leftover tasks.
Reports contain fixed synthetic identities and resource observations, not Tokens,
private keys, message contents, raw server logs or installation paths.

The Python and JS clients connect to different real ingress nodes, and a second
Python client connects to the third. Every workload cycle checks four 2 KB Unicode
messages, at up to five cycles per second. SENDACK and RECV must agree on ID and
sequence and preserve the exact payload. Application inboxes deduplicate a bounded
8,192-ID window while separately counting raw duplicate callbacks.

The Python acceptance clients override heartbeat to 5 seconds, Pong and connection
deadlines to 3 seconds, request timeout to 8 seconds, and reconnect to 20 attempts
starting at 0.5 seconds with a 2-second cap. Queue limits retain SDK defaults.
These bounded fault-test settings differ from the SDK defaults documented in the
README; the installed runtime itself is unchanged. JS uses its SDK defaults.

One fault drops downstream bytes after the peer receives a SEND, then cuts the
transport. The pending operation must report `CONNECTION_LOST`, reconnect and
recover without replaying that SEND. This repeats every five minutes. A separate
fault kills and restarts ingress node 1 using the same data. Token rotation through
node 2 must reject the old credential and accept the new one on all three nodes.
Fresh clients use the new Token; the SDK does not refresh credentials itself.
Transport `recovery_seconds` includes the one-second outage and a one-second
post-reconnect no-replay observation, so it is not a pure connection latency.

Resource samples every 30 seconds include Python harness RSS (both Python SDK
clients, TLS proxies and bookkeeping), JS RSS, each server's RSS, file descriptors,
asyncio tasks and proxy connections. End-to-start client RSS growth is bounded at
32 MiB, descriptors at +8 and tasks at +4; all sampled healthy proxy counts must
remain `[1, 1, 1]`. These are bounded acceptance thresholds, not universal leak or
capacity guarantees. Server RSS includes persisted workload growth and is reported
separately. Public presence must confirm all four identities offline after cleanup.

## Continuous integration

`cluster-acceptance.yml` runs an independent installed wheel on Linux for Python
3.11 / websockets 15.0.1 and Python 3.14 / websockets 17.1 when relevant PR/main
files change. Each job executes the fault suite followed by 60 seconds of traffic.
Manual dispatch selects an exact PyPI 0.1.0 artifact or the current source wheel,
and 60, 1,800 or 3,600 workload seconds. Jobs have a 75-minute outer limit and upload
only the JSON receipt. All actions and external source revisions are pinned;
permissions are read-only and there are no cloud resources or recurring schedules.

The harness checks the clean product VCS stamp, clean JS source revision, pip
installation version/source, and the exact published wheel hash in PyPI mode.
Receipts retain hashes of the harness files and server executable, with client and
dependency versions. A wheel run is candidate evidence, not a PyPI publication.

The source pins and local dependency versions are recorded independently. The
local macOS consumers used Node 22.12.0; hosted Linux CI uses Node 24.3.0.
