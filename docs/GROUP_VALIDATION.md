# Group installed-package validation — 2026-09-08

Python PyPI **0.1.0** passed the group scenario with three real server processes,
256 hash slots, 12 physical Slots, three replicas, private-CA WSS and Token
validation. Three Python clients and one actual JS client authenticate on nodes
`[1, 2, 3, 1]`. Two groups and 13 phases match 16 group deliveries. The interactive
CLI separately sends to three members, receives a reply, displays rejection code
3, and exits on `/quit`. SDK runtime and the published package remain unchanged.

## Exact identities

- PyPI: `wukong-easy-sdk==0.1.0`, release source
  `ec2c62c73eca29be99ac15ba76ff7466c13617d5`.
- Public wheel SHA-256:
  `d653a73537aa0ca66aa21eb4a6ab2f60bfc5b819e018f233a8a9c9502671cf48`.
- Fixed server source: `2a295e0d9881ef5356728a85d56b052c4b0d9c86`, with a clean
  VCS stamp and executable hash checked by the harness. This server pin includes
  [the recipient-cache repair](https://github.com/WuKongIM/WuKongIM/pull/920).
- JS 2.0.4: clean source `9c03c98c725982fac224cd1d3b52456eae983975`.
- Local executed harness/example source:
  `527f37c876326e7ad3cc48c89828c4c3ffed09fc`. Every receipt binds fixture/example
  file hashes. macOS used Node 22.12.0; hosted CI uses Node 24.3.0.

The local consumers reinstalled the exact PyPI wheel using `--no-cache-dir`,
`--no-deps`, an explicit PyPI index, and a new pip installation report. The
separate virtual environments retain pinned websockets/trustme/psutil fixture
dependencies; they do not install the checkout. Candidate wheel CI is identified
separately and is not a PyPI download receipt.

## Successful local runs

| Receipt | Python / websockets | Total elapsed | Four-client recovery | Phases / group deliveries | Result |
| --- | --- | --- | --- | --- | --- |
| [macos-pypi-python311.json](receipts/group-20260908/macos-pypi-python311.json) | 3.11.12 / 15.0.1 | 53.979 s | 1.462 s | 13 / 16 | Passed |
| [macos-pypi-python314.json](receipts/group-20260908/macos-pypi-python314.json) | 3.14.7 / 17.1 | 54.383 s | 1.411 s | 13 / 16 | Passed |

Recovery includes the one-second intentional outage and waiting for all four
public CONNECT events. Each phase also observes every excluded inbox for one
second after expected deliveries or a denied SEND. Duplicate callbacks were zero;
public presence confirmed all identities offline, and cleanup left zero owned
server/JS/example processes, proxy connections and extra asyncio tasks.

The 13 phases cover member fanout, group isolation, nonmember rejection, joining,
removed JS rejection and exclusion, Python blacklist rejection, reconnect with
both nonmember and blacklist permissions preserved, blacklist removal, JS rejoin,
JS blacklist rejection and restoration. Rejection codes are 3 (nonmember under
`allow_stranger=0`) and 4 (blacklisted sender), through the public Python error or
JS request result/error. Successful messages match sender, channel, payload,
message ID and positive increasing per-channel sequence.

## Server repair and limits

The original server `e7ef61ba702e045648b9fa535f051e5b2ee4a1db` reproduced an
incorrect membership result: Bob received after removal and Dave missed a message
after joining. The server now reads mutable recipient versions and subscriber
pages from the current Slot leader; benchmark preparation snapshots no longer
supply product fanout. Snapshot reads use 1,024-row pages instead of a sentinel
limit that caused huge storage preallocation in an intermediate candidate.
Existing person metadata and versioned group snapshot reuse remain in place.

Only the final fixed-server runs above count as successful acceptance. Intermediate
server candidates and hosted missed-member-delivery attempts are not folded
into those results. Hosted diagnostics and their scope are recorded below.

This is online functionality for four clients, not a large-group benchmark,
offline-history recovery, exactly-once guarantee or a new 30-minute soak.
The historical [person WSS soak](CLUSTER_VALIDATION.md) retains its own older
server and harness pins. Installing Python 0.1.0 does not update a server: deploy
the fixed source or a future server release that includes it. No new native server
release is claimed here. Follow [GROUP_ACCEPTANCE.md](GROUP_ACCEPTANCE.md) using the
recorded group-specific server and harness pins, not the original `v0.1.0` tag.

## Hosted CI and diagnostic boundary

[Group CI run 34208513024](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34208513024)
passed both independent candidate-wheel environments. Source head
`ddfe57098f91a5c8b7d0e2131e6cfc4321f9105e` adds a passive observer of native
WebSocket message events: it records only frame classification and received
message IDs, with bounded counters/retention. It does not replace transport or
change frames. Each receipt records its GitHub PR merge revision and file hashes.

| Receipt | Python / websockets | Total elapsed | Phases / group deliveries | Result |
| --- | --- | --- | --- | --- |
| [linux-wheel-python311.json](receipts/group-20260908/linux-wheel-python311.json) | 3.11.16 / 15.0.1 | 27.223 s | 13 / 16 | Passed |
| [linux-wheel-python314.json](receipts/group-20260908/linux-wheel-python314.json) | 3.14.7 / 17.1 | 23.264 s | 13 / 16 | Passed |

The six Linux/macOS/Windows × Python 3.11/3.14 jobs passed 43 unit and 21 WS/WSS
integration tests, Ruff, strict mypy, package build and Twine:
[run 34208513088](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34208513088).

An [earlier hosted Python 3.11 attempt](receipts/group-20260908/linux-wheel-python311-earlier-miss.json)
at source head `527f37c876326e7ad3cc48c89828c4c3ffed09fc` missed Bob's JS delivery
after Dave joined: Alice and Carol received the accepted message, while all four
clients retained their original connection and reported no error or duplicate.
The cause was not established. Three additional local Node 24.3.0 diagnostic
runs and the subsequent hosted diagnostic run passed; these do **not** prove that
the intermittent miss is fixed. This observation remains separate from the confirmed
server stale-membership and oversized-allocation repairs. The native event
observer provides evidence for a future recurrence; it is not a runtime fix.

The intermittent miss is tracked in [issue #7](https://github.com/WuKongIM/WuKongEasySDK-Python/issues/7).
The unchanged historical person scenario also passed the updated diagnostic bridge
on both Linux consumer versions in [run 34208513040](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34208513040).

A later [Python 3.14 receipt](receipts/group-20260908/linux-wheel-python314-later-miss.json)
from [run 34209083205](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34209083205)
missed Python Carol in the same phase. Alice and JS Bob received; Bob's native
WebSocket observer also saw the accepted message ID. Connections, errors and
duplicates remained unchanged. This rules out a JS-only symptom. Group acceptance
is still under investigation; passing attempts do not establish reliability.
Failure collection now captures bounded delivery metrics, fixed delivery-failure
log fields and public presence before the owned cluster is destroyed.
