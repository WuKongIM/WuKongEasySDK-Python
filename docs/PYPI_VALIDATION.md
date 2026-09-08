# PyPI 0.1.0 validation — 2026-09-08

Package: [wukong-easy-sdk 0.1.0](https://pypi.org/project/wukong-easy-sdk/0.1.0/).
Release: [v0.1.0](https://github.com/WuKongIM/WuKongEasySDK-Python/releases/tag/v0.1.0).
Exact source: [`ec2c62c73eca29be99ac15ba76ff7466c13617d5`](https://github.com/WuKongIM/WuKongEasySDK-Python/commit/ec2c62c73eca29be99ac15ba76ff7466c13617d5).

## Publication and artifact identity

The [publish workflow](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34195215065) passed tag/version/changelog and main
ancestry gates, protocol tests, wheel/sdist builds, strict Twine metadata checks,
and tests from the built wheel before uploading those same artifacts through PyPI
Trusted Publishing. The binding is `WuKongIM/WuKongEasySDK-Python`, `publish.yml`,
environment `pypi`; GitHub permits that environment only for tags matching `v*`.

The public PyPI JSON API and the workflow downloads agree on both SHA-256 values:

| Artifact | Bytes | SHA-256 |
| --- | --- | --- |
| `wukong_easy_sdk-0.1.0-py3-none-any.whl` | 16575 | `d653a73537aa0ca66aa21eb4a6ab2f60bfc5b819e018f233a8a9c9502671cf48` |
| `wukong_easy_sdk-0.1.0.tar.gz` | 100470 | `774b04d822eeaab32217258bf0c896c9b2631181b568f6b3ccf123151e667fbd` |

Metadata version is 2.4 for upload-tool compatibility. The package requires
Python 3.11+ and `websockets>=15.0.1,<18`. These files were published once;
post-publication documentation commits do not change the immutable release.

## Installed-package acceptance

Host: macOS, Apple Silicon. Both environments were created empty, then installed
`wukong-easy-sdk==0.1.0` using pip with `--no-cache-dir` and the explicit
`https://pypi.org/simple` index. Both pip installation reports contain the exact
public wheel URL and SHA-256 above. Imports resolve inside each virtual
environment's `site-packages`; no editable or source SDK was installed.

| Environment | Protocol and release gates | Real product/JS harness |
| --- | --- | --- |
| CPython 3.11.12, websockets 15.0.1 | 64 passed | Passed |
| CPython 3.14.7, websockets 17.1 | 64 passed | Passed |

The 64 tests comprise 31 protocol units, 21 WS/WSS integration cases, and 12
release-metadata gates. The [source CI at the exact release commit](https://github.com/WuKongIM/WuKongEasySDK-Python/actions/runs/34195106718)
also passed Linux/macOS/Windows × Python 3.11/3.14, including lint, formatting,
strict mypy, tests, package builds and metadata checks.

Both installed-package environments executed `tests/product.py` against:

- WuKongIM source `0348c0539bbee420a859439695acdac911afa854`, a temporary
  Token-authenticated single-node cluster with 256 hash slots and 8 physical Slots.
- Actual JS SDK 2.0.4 source `9c03c98c725982fac224cd1d3b52456eae983975`, built
  with `npm ci` and `npm run build`; this is source-built JS, not an npm receipt.

Passed: Python/Python and Python/JS bidirectional Unicode/Emoji and 2 KB messages,
matching SENDACK/RECV identities, heartbeats, manual reconnect, invalid-Token
rejection, and public online-status cleanup. Each harness stopped only its own
processes and removed its temporary data directory.

## Reproduce

Prepare the exact server binary and JS build as described in
[the source validation record](VALIDATION.md), then use a fresh virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --no-cache-dir --index-url https://pypi.org/simple "wukong-easy-sdk==0.1.0"
python -m pip install --index-url https://pypi.org/simple pytest pytest-asyncio trustme
git clone --branch v0.1.0 --depth 1 https://github.com/WuKongIM/WuKongEasySDK-Python.git
cd WuKongEasySDK-Python
python -m pytest -o addopts=''
python tests/product.py --server /absolute/path/to/wukongim \
  --js-entry /absolute/path/to/WuKongEasySDK-JS/dist/cjs/index.js
```

For the minimum-dependency case, additionally pin `websockets==15.0.1`.

## Limits

Real product acceptance covers WS online person messaging and manual reconnect.
Independent protocol tests cover WSS certificate validation, automatic recovery,
cancellation and bounded queues. This record does not establish production WSS
proxy behavior, multi-node failover, group fanout capacity, long-running stability,
Token-expiry policy, offline/history/push functionality, or JS npm package identity.
No cloud resources were used.
