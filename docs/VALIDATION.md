# Validation record — 2026-09-08

Implementation source: [`74650d2df93e52641973926a7bfdda37ab624811`](https://github.com/WuKongIM/WuKongEasySDK-Python/commit/74650d2df93e52641973926a7bfdda37ab624811),
project version `0.1.0`. The runtime implementation is unchanged by later documentation and test-fixture
commits. The cross-platform suite uses the IPv4 loopback fixture at
`61e6e817c45c20921dde4b8919a1ab58fee6c0ad`. This is source and locally built
wheel evidence collected before PyPI publication.

## Local results

Host: macOS, Apple Silicon.

| Environment / check | Result |
| --- | --- |
| CPython 3.12.10, websockets 17.1, locked development environment | 31 unit + 21 WS/WSS integration tests passed |
| CPython 3.11.12, websockets 15.0.1, installed wheel in a separate environment | All 52 tests passed; verifies the supported minimum versions |
| CPython 3.14.7, websockets 17.1, installed wheel in a separate environment | All 52 tests passed |
| Ruff lint and formatting | Passed |
| Strict mypy | Passed for all four source modules |
| `uv build` | Source distribution and `py3-none-any` wheel built successfully |

The protocol tests use bounded local servers. They cover Unicode/Emoji, object
and JSON/Base64 Payload profiles, 64-bit identity, CONNECT rejection through both
result and RPC-error envelopes, shared/cancelled connection waiters, auth deadline,
manual reconnect and close, async callback replies, listener removal and callback
error isolation, callback-owned destruction, cancellation and timeouts, request
count/byte admission, event overflow without ACKing dropped messages, correlated
null heartbeat replies, uncorrelated Pong rejection, reconnect and retry exhaustion,
terminal disconnect/auth/protocol failure, and no automatic SEND replay.

WSS tests verify a private CA, reject untrusted certificates and mismatched
hostnames, and reject oversized frames. Global DEBUG logging tests ensure the
SDK does not disclose credentials, Payloads, peer response text or data.

The read-only CI workflow passed all six Linux/macOS/Windows × Python 3.11/3.14
jobs at `61e6e817c45c20921dde4b8919a1ab58fee6c0ad`: [hosted run
34191290715](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34191290715).
Each job passed all 52 tests, lint, formatting, strict types, and sdist/wheel builds.
The first run exposed a test-fixture address mismatch on Windows (IPv4 listener
versus localhost resolution); matching the client address to the listener resolved
that failure. No SDK runtime change was required.

## Real product and JavaScript interoperability

Product source: WuKongIM
[`0348c0539bbee420a859439695acdac911afa854`](https://github.com/WuKongIM/WuKongIM/commit/0348c0539bbee420a859439695acdac911afa854).
Actual JS SDK: `easyjssdk` 2.0.4, source
[`9c03c98c725982fac224cd1d3b52456eae983975`](https://github.com/WuKongIM/WuKongEasySDK-JS/commit/9c03c98c725982fac224cd1d3b52456eae983975),
built using `npm ci` and `npm run build`. This executes the JS SDK, not a synthetic
wire-profile client. The JS dependency was built from source, not resolved as an
installed npm release receipt.

The harness starts a real `cmd/wukongim` single-node cluster using 256 hash slots,
8 physical Slots, one replica, Token authentication enabled, random loopback ports,
an isolated temporary data directory, and the public WSMux `/ws` endpoint.
Tokens are provisioned through public `/user/token` for Desktop device flag `2`.

Passed:

- Python Alice → Python Bob and reverse: exact Unicode Payload, matching SENDACK
  and RECV message ID/sequence, plus heartbeats for both peers.
- Manual disconnect, reconnect with the same identity, then another delivered message.
- Invalid Token rejection with reason code `2`.
- Python Alice → actual JS Bob → Python Alice for Unicode/Emoji and 2 KB content.
- Public `/user/onlinestatus` confirms both users offline after Python and JS cleanup.
- Only the harness's own processes are stopped and its temporary directory removed.

Reproduce from the exact source checkouts:

```sh
# WuKongIM checkout at the product revision above
GOWORK=off go build -o /tmp/wukongim-python-acceptance ./cmd/wukongim

# WuKongEasySDK-JS checkout at the JS revision above
npm ci --no-audit --no-fund
npm run build

# WuKongEasySDK-Python checkout
uv sync --locked
uv run pytest
uv run pytest -m integration
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv build
uv run python tests/product.py --server /tmp/wukongim-python-acceptance \
  --js-entry /absolute/path/to/WuKongEasySDK-JS/dist/cjs/index.js
```

## Limits

The product run verifies WS online person messaging and manual reconnect on one
local cluster. Automatic transport recovery and WSS are covered by independent
protocol tests. These receipts do not establish production WSS proxy behavior,
multi-node failover, high-capacity/group fanout, long-running stability, Token
expiry policy, or offline/history/push functionality. No cloud resources were used.
