# Group acceptance

Approved seams for this task: installed Python/JS SDK public methods and events,
Product HTTP management of synthetic users, channels, membership and blacklist,
owned local process/TLS/network boundaries, and the interactive example CLI.
The user approved implementation, validation, CI and bilingual documentation.

Four clients span three real ingress nodes, with two groups. Check member fanout,
channel isolation, add/remove/readd, nonmember and blacklist rejection, reconnect
preserving membership and permissions, and the runnable group example. Management
belongs to a trusted backend; the example receives credentials and a group ID.

Reuse the isolated cluster in [CLUSTER_ACCEPTANCE.md](CLUSTER_ACCEPTANCE.md),
but build the group-specific server pin below.
This is functional acceptance, not a new soak or group capacity benchmark.
Negative delivery checks have a bounded observation window. Delivery duplicates
remain observable; the test cannot establish an exactly-once guarantee.

Instructions frozen from documentation source
`9842e6f2245aec2748efb438fe3c5613d29abf1c`:

| File | SHA-256 |
| --- | --- |
| `AGENTS.md` | `de01b8e88d03a98ce4c4f20e09c2952c54b5bceefac7f942b6171f4bc99b7c41` |
| `docs-site/FLOW.md` | `023d610c04a33e6a09719b30f5bcb0d01dd572f134c4461e0d63ddaef0f0ec28` |

The SDK source `856458abfbfd0d6281f6c71af5fda7a8dcef7167` has no applicable
AGENTS, FLOW, CONTEXT or ADR files.

## Reproduce

Build server `2a295e0d9881ef5356728a85d56b052c4b0d9c86`
and JS `9c03c98c725982fac224cd1d3b52456eae983975`
using the clean-clone steps in `CLUSTER_ACCEPTANCE.md`. The server pin includes
the cross-ingress member-cache fix; the older person-soak server is insufficient
for this group scenario. Use a separate
Python environment with the public `wukong-easy-sdk==0.1.0`, `trustme==1.2.1`,
`psutil==7.2.2`, and websockets 15.0.1 (Python 3.11) or 17.1 (Python 3.14).
Retain pip's `--report` JSON from an explicit PyPI installation. Run from the
harness revision recorded in `GROUP_VALIDATION.md`, not the older `v0.1.0` tag:

```sh
/absolute/path/to/consumer/bin/python tests/group.py \
  --server /absolute/path/to/wukongim \
  --js-entry /absolute/path/to/js/dist/cjs/index.js \
  --install-report /absolute/path/to/install.json --package-source pypi \
  --output /tmp/python-group-report.json
```

The harness checks the installed distribution and public wheel SHA-256, clean
server/JS source stamps, and records all fixture/example hashes. No editable SDK
installation is accepted. All listeners are loopback-only. Tokens, private keys,
message bodies and installation paths are excluded from receipts.

Each send checks all four client inboxes, message identity/sequence, channel,
sender and payload, followed by one second of negative delivery observation.
Raw duplicate callbacks are counted even when the reusable inbox deduplicates.
The two groups explicitly set `allow_stranger=0`: nonmembers must fail with code
3, blacklisted senders with code 4. These are server policy results; Python raises
`WKIMError`, while the pinned JS public request can reject with an error code.
Assertions accept a JS SENDACK reason when returned, but never treat rejection as
success. These configured tests do not imply that every group rejects strangers.

The fixture interrupts all four authenticated WSS connections for one second,
waits for new public CONNECT events on each original ingress, then rechecks both
removed membership and an active blacklist. After restoring permissions it tests
re-added JS sending. The CLI then replaces one Python client and must send to
three members, receive a reply, display a nonmember error, and exit on `/quit`.
Python fault deadlines/retry settings are the explicit overrides documented in
`CLUSTER_ACCEPTANCE.md`; JS retains its defaults. All processes and tasks are
bounded and cleaned up. There is no offline-history or large-group claim.

## CI

The separate `group-acceptance.yml` runs Linux Python 3.11 / websockets 15.0.1 and
Python 3.14 / websockets 17.1 with an independently installed candidate wheel on
relevant PR/main changes. Manual dispatch chooses `pypi` (exact public 0.1.0) or
`wheel`. Each job has a 15-minute outer limit and uploads a JSON receipt for 14
days. It uses pinned Actions, server and JS revisions, read-only permissions,
and no cloud resources or recurring schedule. The existing cluster workflow
continues to cover its separate fault/60-second regression.
