# Changelog

## Unreleased

- Add independent installed-package three-node WSS acceptance for Python/JS
  messaging, transport/ACK loss, node restart, Token rotation and bounded resource
  observations, with a separate CI smoke and manual 30/60-minute workflow.

## 0.1.0 - 2026-09-08

### Added

- Python 3.11+ asyncio client aligned with WuKongEasySDK-JS 2.0.4, with authenticated
  WS/WSS, online messaging, RECVACK, heartbeat, bounded reconnect and custom events.
- Typed public options and events, bounded queues, async lifecycle cleanup,
  an interactive example, bilingual README and source/wheel validation records.

- PyPI Trusted Publishing with tag/version/changelog checks and installed-wheel
  validation before upload.
- Metadata 2.4 for compatibility with the PyPI upload toolchain.
