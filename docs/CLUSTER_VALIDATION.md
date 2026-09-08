# Three-node WSS installed-package validation — 2026-09-08

The PyPI 0.1.0 package completed **1800.032 seconds** of local
three-node WSS workload after the initial fault suite, with **35,380
SENDACK/RECV pairs** matched across the run. No SDK runtime change was needed;
version 0.1.0 and its published artifacts remain unchanged. Six additional received
messages belong to the deliberately withheld-ACK faults and are excluded from the
matched-pair count.

## Exact identities

- Python package: PyPI `wukong-easy-sdk==0.1.0`, released source
  `ec2c62c73eca29be99ac15ba76ff7466c13617d5`.
- Installed public wheel SHA-256:
  `d653a73537aa0ca66aa21eb4a6ab2f60bfc5b819e018f233a8a9c9502671cf48`.
- Product source: `e7ef61ba702e045648b9fa535f051e5b2ee4a1db`; clean VCS stamp verified before startup.
- macOS product binary SHA-256: `a10329d35b697c1473bb91b7c342bcce428e0c0451581bb6383e17a8d9d1743e`.
- JS 2.0.4 built from clean source `9c03c98c725982fac224cd1d3b52456eae983975`.
- Executed harness: [`1bda54d04154d246be04c8c5452586d77a932333`](https://github.com/WuKongIM/WuKongEasySDK-Python/commit/1bda54d04154d246be04c8c5452586d77a932333).
  Each JSON receipt also records the three harness-file hashes.
- Local host: `macOS-15.1-arm64-arm-64bit-Mach-O`; CPython 3.14.7, websockets
  17.1, Node v22.12.0. Linux CI uses Node 24.3.0.

The PyPI consumers used fresh virtual environments and `pip --no-cache-dir` with
an explicit `https://pypi.org/simple` index. The harness verifies the pip installation
report and exact public wheel hash and rejects editable installs. Hosted wheel
runs independently install the candidate wheel; their identical wheel hash does
not turn them into PyPI download receipts.

## Runs

| Raw receipt | Python / websockets | Workload after faults | Matched SENDACK/RECV | Result |
| --- | --- | --- | --- | --- |
| [macos-pypi-python314-30m.json](receipts/cluster-20260908/macos-pypi-python314-30m.json) | 3.14.7 / 17.1 | 1800.032 s | 35,380 | Passed |
| [macos-pypi-python311-smoke.json](receipts/cluster-20260908/macos-pypi-python311-smoke.json) | 3.11.12 / 15.0.1 | 60.028 s | 1,068 | Passed |
| [linux-wheel-python311-smoke.json](receipts/cluster-20260908/linux-wheel-python311-smoke.json) | 3.11.16 / 15.0.1 | 60.028 s | 1,212 | Passed |
| [linux-wheel-python314-smoke.json](receipts/cluster-20260908/linux-wheel-python314-smoke.json) | 3.14.7 / 17.1 | 60.030 s | 1,212 | Passed |

Hosted acceptance: [run 34199043056](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34199043056).
The six Linux/macOS/Windows × Python 3.11/3.14 unit/integration/build jobs also
passed at the harness commit: [CI run 34199042976](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34199042976).
Each ran 43 unit and 21 WS/WSS integration tests, Ruff, strict mypy, build and Twine.

## Fault and resource observations

The cluster has 256 hash slots, 12 physical Slots and three Slot replicas. Token
authentication is enabled. Python Alice, JS Bob and Python Carol authenticate on
nodes 1, 2 and 3, through three private-CA TLS proxies. Each workload cycle checks
four 2 KB Unicode messages, with an upper target of five cycles per second.
The [acceptance guide](CLUSTER_ACCEPTANCE.md) records the configured deadlines and
reconnect limits; these are fault-test overrides, not a claim about default timings.

- 6 withheld-ACK/transport cuts passed: each SEND reached its receiver,
  the sender received `CONNECTION_LOST`, automatic WSS reconnection succeeded, and
  the SDK did not replay the ambiguous SEND. The reported observation intervals
  were 2.308–2.518 seconds, including a one-second outage and
  one-second post-reconnect observation. One occurs before the workload and five
  at the 5/10/15/20/25-minute marks.
- Killing and restarting ingress node 1 with its same durable directory recovered
  in 4.869 seconds; subsequent cross-node messages passed.
- Backend Token rotation rejected the old credential and accepted the new one on
  all three nodes. The application created fresh clients with the new Token.
- Raw duplicate callbacks observed: **0**. The application retains a bounded
  8,192-ID deduplication window per inbox. This result does not promise exactly-once delivery.
- Healthy samples retained 19 asyncio tasks and exactly one live connection
  per proxy. Public presence confirmed all four synthetic identities offline.
- Cleanup left **zero** owned processes, proxy connections or extra asyncio tasks.

RSS values are MiB and peaks are sampled every 30 seconds. The final-ten-minute
slope is a least-squares summary of those samples, not a production leak guarantee.

| Process | First RSS | Sampled peak RSS | Final RSS | Final 10 min MiB/min | First → final FDs |
| --- | --- | --- | --- | --- | --- |
| Python harness and two SDK clients | 42.78 | 42.78 | 28.58 | -1.273 | 23 → 23 |
| JS peer | 45.69 | 57.69 | 30.59 | -1.935 | 15 → 15 |

All end-to-start guardrails passed: client RSS +32 MiB, descriptors +8 and tasks +4.
Python RSS includes both SDK clients, TLS proxies and test bookkeeping. The raw
receipts also retain each server's resources; persistent message growth belongs
to the server workload and is not treated as an SDK memory leak.

## Scope and reproduction

Follow [CLUSTER_ACCEPTANCE.md](CLUSTER_ACCEPTANCE.md) using the exact harness commit
above. The 30-minute duration excludes startup and initial fault checks; total local
elapsed time was 1835.780 seconds. Short CI and the Python 3.11 run are
separate 60-second receipts, not additional 30-minute runs.

This verifies online person messaging on one local three-node cluster, private-CA
TLS termination, bounded fault recovery and cleanup. It does not establish group
fanout capacity, offline history recovery, automatic Token refresh, arbitrary
Internet proxies, multi-host partitions or production-scale leak freedom.
