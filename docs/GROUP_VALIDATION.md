# Group installed-package validation — 2026-09-08

The final group fixture passed in two Python PyPI consumers and six independent
Linux candidate-wheel starts. Four actual Python/JS clients span three real
server processes with 256 hash slots, 12 logical Slots, three replicas,
private-CA WSS and Token validation. All clients log in after the fixture's
initial preferred-leader placement converges. Two groups and 13 phases match
16 group deliveries in every run. The CLI separately sends to three members,
receives a reply, displays rejection code 3 and exits on `/quit`.

SDK runtime and the public PyPI version remain unchanged. The startup condition
corrects the test fixture; it does not repair online delivery during server
Slot leadership migration. Failed attempts and the diagnosis are retained below.

## Exact identities

- PyPI: `wukong-easy-sdk==0.1.0`, release source
  `ec2c62c73eca29be99ac15ba76ff7466c13617d5`.
- Public wheel SHA-256:
  `d653a73537aa0ca66aa21eb4a6ab2f60bfc5b819e018f233a8a9c9502671cf48`.
- Fixed server source: `2a295e0d9881ef5356728a85d56b052c4b0d9c86`;
  each receipt checks its clean VCS stamp and records the executable hash.
  [Server repair PR #920](https://github.com/WuKongIM/WuKongIM/pull/920) is merged.
- JS 2.0.4: clean source `9c03c98c725982fac224cd1d3b52456eae983975`.
- Harness and example source: `5e67c20d19756481624c5ef1b5fa49784bcfc4bf`.
  All eight receipts' fixture/example hashes match this commit. CI additionally
  records its exact GitHub PR merge revision. All final runs use Node 24.3.0.

The local consumers reinstalled the exact PyPI wheel with `--no-cache-dir`,
`--no-deps`, an explicit PyPI index and a new pip installation report. Their
separate virtual environments retain pinned websockets/trustme/psutil fixture
dependencies and do not install the checkout. Linux candidate-wheel receipts
identify their independently built and installed artifacts separately; they are
not PyPI download evidence.

## Final results

Every row passed 13 phases / 16 group deliveries, the CLI and cleanup.
Startup is the observed placement wait after `/readyz`, before client login.

| Receipt | Consumer | Python / websockets | Total elapsed | Startup |
| --- | --- | --- | --- | --- |
| [macos-pypi-python311-settled.json](receipts/group-20260908/macos-pypi-python311-settled.json) | PyPI / macOS | 3.11.12 / 15.0.1 | 52.802 s | 0.009 s |
| [macos-pypi-python314-settled.json](receipts/group-20260908/macos-pypi-python314-settled.json) | PyPI / macOS | 3.14.7 / 17.1 | 53.219 s | 0.008 s |
| [linux-wheel-python311-settled-1.json](receipts/group-20260908/linux-wheel-python311-settled-1.json) | Candidate wheel / Linux | 3.11.16 / 15.0.1 | 26.663 s | 2.255 s |
| [linux-wheel-python311-settled-2.json](receipts/group-20260908/linux-wheel-python311-settled-2.json) | Candidate wheel / Linux | 3.11.16 / 15.0.1 | 21.945 s | 0.006 s |
| [linux-wheel-python311-settled-3.json](receipts/group-20260908/linux-wheel-python311-settled-3.json) | Candidate wheel / Linux | 3.11.16 / 15.0.1 | 22.221 s | 0.006 s |
| [linux-wheel-python314-settled-1.json](receipts/group-20260908/linux-wheel-python314-settled-1.json) | Candidate wheel / Linux | 3.14.7 / 17.1 | 23.96 s | 0.009 s |
| [linux-wheel-python314-settled-2.json](receipts/group-20260908/linux-wheel-python314-settled-2.json) | Candidate wheel / Linux | 3.14.7 / 17.1 | 36.559 s | 11.874 s |
| [linux-wheel-python314-settled-3.json](receipts/group-20260908/linux-wheel-python314-settled-3.json) | Candidate wheel / Linux | 3.14.7 / 17.1 | 22.841 s | 0.008 s |

[Group CI run 34211730596](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34211730596)
ran three fresh clusters per Python environment and stopped on no failure.
One run required 11.874 seconds to reach initial placement; it then passed the
unchanged scenario. This provides a direct check of the admission condition.
The six Linux/macOS/Windows × Python 3.11/3.14 jobs passed 43 unit and 21 WS/WSS
integration tests, Ruff, strict mypy, build and Twine in
[SDK CI run 34211730496](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34211730496).

The phases cover fanout, group isolation, nonmember rejection, joining, removed
JS rejection/exclusion, Python blacklist rejection, four-client reconnect with
membership and blacklist preserved, blacklist removal, JS rejoin, JS blacklist
rejection and restoration. Successful messages match payload, channel, sender,
message ID and a positive increasing per-channel sequence. Rejection codes are
3 (nonmember with `allow_stranger=0`) and 4 (blacklisted sender).

Every excluded inbox is observed for one second after deliveries or rejection;
raw duplicate callbacks are checked despite the reusable inbox's deduplication.
The outage interrupts all four WSS connections for one second. Recovery waits
for their public CONNECT events on ingress nodes `[1, 2, 3, 1]`.
All runs report zero duplicates, public presence confirmed offline at shutdown,
and zero remaining owned server/JS/example processes, proxy connections or
extra asyncio tasks.

## Confirmed server membership repair

The original server `e7ef61ba702e045648b9fa535f051e5b2ee4a1db` delivered to Bob
after removal and missed Dave after joining through another ingress. The fixed
server reads mutable recipient versions and subscriber pages from the current
Slot leader; benchmark snapshots no longer supply product fanout. Snapshot
reads use 1,024-row pages instead of the sentinel limit that caused storage
preallocation failure in an intermediate candidate. Person metadata and
versioned group snapshot reuse remain in place.

Installing Python 0.1.0 does not update a server. Deploy the recorded fixed
source or a future release containing it. This record does not claim a new
native server package release.

## Startup diagnosis and preserved failures

[Run 34211203123](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34211203123)
at harness head `03994e5` stopped on the second Python 3.11 cluster and third
Python 3.14 cluster. It retained all preceding attempts. The
[3.11 failure](receipts/group-20260908/linux-wheel-python311-startup-transition.json)
and [3.14 failure](receipts/group-20260908/linux-wheel-python314-startup-transition.json)
include initial/failure topology, phase times, native JS frame IDs, bounded
delivery/presence metrics and leader-transition log fields.

In the 3.14 case, Bob maps to hash slot 46 / logical Slot 3. Its initial leader
was node 2, while its preferred leader was node 3. Node 3 became leader at
09:41:12.308 UTC; Dave sent at 09:41:14.456 UTC. Bob then had no authoritative
presence or received wire frame despite retaining his original connection.
All nodes reported zero expired routes. The 3.11 failure likewise began with
Slots 3, 6 and 9 awaiting preferred-leader convergence.

This follows the server's existing
[presence touch design](https://github.com/WuKongIM/WuKongIM/blob/2a295e0d9881ef5356728a85d56b052c4b0d9c86/docs/superpowers/specs/2026-06-01-internalv2-presence-touch-design.md):
a changed authority starts empty and reconstructs routes from the next valid
owner activity. Python's test heartbeat is five seconds; the pinned JS default
is 25 seconds. `/readyz` alone did not establish stable initial placement.

The corrected fixture waits for all 12 Slots to report quorum, matched
replication, three healthy voters, actual/preferred leader agreement, no pending
leader transfer and no active Controller task. It records initial/admitted
snapshots and has a 60-second deadline within the existing scenario timeout.
All recipients, receive deadlines, errors and exclusion windows are unchanged.
No SEND is replayed, and no failed attempt is retried or discarded.

Earlier [JS-miss](receipts/group-20260908/linux-wheel-python311-earlier-miss.json)
and [Python-miss](receipts/group-20260908/linux-wheel-python314-later-miss.json)
receipts lack full topology evidence, so their individual transitions cannot be
retrospectively proven. Earlier successful macOS/Linux receipts remain in the
same directory as historical diagnostic attempts and do not replace the final
rows above. [Issue #7](https://github.com/WuKongIM/WuKongEasySDK-Python/issues/7)
records the diagnosis and correction.

This is online functionality for four clients after initial placement, not a
large-group benchmark, an exactly-once guarantee, offline-history recovery,
uninterrupted delivery during authority migration or a new 30-minute soak.
The historical [person WSS soak](CLUSTER_VALIDATION.md) retains its older server
and harness pins. Follow [GROUP_ACCEPTANCE.md](GROUP_ACCEPTANCE.md) using the
group-specific pins above; the original `v0.1.0` tag lacks the group example.
