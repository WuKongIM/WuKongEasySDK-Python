# Migrating from WuKongEasySDK-JS 2.0.4

The reference is commit `9c03c98c725982fac224cd1d3b52456eae983975`.

| JavaScript | Python |
| --- | --- |
| `WKIM.init(url, { uid, token })` | `WKIM.init(url, AuthOptions(uid, token))` |
| `deviceId`, `deviceFlag` | `device_id`, `device_flag` in `AuthOptions` |
| `WKIMChannelType.Person`, `.Group` | `WKIMChannelType.PERSON`, `.GROUP` |
| `WKIMDeviceFlag.App`, `.Web`, `.Desktop` | `WKIMDeviceFlag.APP`, `.WEB`, `.DESKTOP` |
| `WKIMEvent.Message` | `WKIMEvent.MESSAGE` |
| `WKIMEvent.CustomEvent`, `.SendAck` | `WKIMEvent.CUSTOM_EVENT`, `.SEND_ACK` |
| `im.on(event, callback)` / `im.off(event, callback)` | Same names; sync or async one-argument callback |
| `await im.connect()` | `await im.connect()`, returns the CONNECT dictionary |
| `await im.send(id, type, payload, options)` | `await im.send(id, type, payload, client_msg_no=..., header=...)` |
| `im.isConnected` | `im.is_connected` |
| `im.disconnect()` / `im.destroy()` | `await im.disconnect()` / `await im.destroy()` |
| `message.payload`, `ack.reasonCode` | `message["payload"]`, `ack["reasonCode"]` |
| `debugLogging` | `WKIMOptions(debug_logging=True)` |

Python defaults to DESKTOP `2`, while JS defaults to WEB `1`. All instances are
independent. Python accepts dictionaries or arrays and encodes their UTF-8 JSON
as Base64, uses camelCase JSON-RPC parameters and text WebSocket frames, and
keeps IDs as strings and sequence integers exact. It preserves an explicit
`header={"redDot": False}`. It emits `SEND_ACK` for successful `send()` operations.

`connect()` checks `reasonCode == 1`, including servers that reject through a
normal result envelope rather than an RPC error. `ping()` accepts a correlated
null result but never treats an uncorrelated Pong notification as its response.
Terminal server disconnects and auth rejection stop automatic retry. Shared
connect cancellation, bounded queues and async shutdown are documented in the
[README](../README.md).

Both SDKs implement lightweight online messaging. Optional stream/topic/header
flags need server support; these APIs do not imply offline recovery, batch RPC,
subscriptions, push, or message persistence on the client.
