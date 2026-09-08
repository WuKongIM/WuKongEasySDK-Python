# WuKongEasySDK-Python

[English README](README.md)

WuKongIM 轻量 Python SDK，要求 Python 3.11+，基于 `asyncio` 与 `websockets`。
参考 [WuKongEasySDK-JS v2.0.4](https://github.com/WuKongIM/WuKongEasySDK-JS/tree/9c03c98c725982fac224cd1d3b52456eae983975)
实现 CONNECT 鉴权、在线 SEND/SENDACK、RECV/RECVACK、心跳、自动重连和自定义事件。

## 安装

工程版本 `0.1.0`，当前通过源码安装，**尚未发布到 PyPI**。可构建 wheel 和 sdist。

```sh
git clone https://github.com/WuKongIM/WuKongEasySDK-Python.git
cd WuKongEasySDK-Python
python3 -m venv .venv
source .venv/bin/activate
# Windows PowerShell 使用 .venv\Scripts\Activate.ps1
python -m pip install .
```

正式接入时先 checkout 已验证的精确 commit。分发名为 `wukong-easy-sdk`，导入名为
`wukong_easy_sdk`，依赖 `websockets>=15.0.1,<18`；`uv.lock` 固定开发依赖。

## 连接、监听与发送

由受信业务后端提供 `uid`、`token` 和 WebSocket URL。Python 默认设备类别为
DESKTOP/PC `2`，必须与后端保存 Token 的类别一致；APP `0`、WEB `1`。
客户端不调用 Product HTTP 管理接口。默认本机地址 `ws://127.0.0.1:5200`，
仅当 listener 或代理配置了 `/ws` 时才在 URL 中加上该路径，生产使用 WSS。

```python
import asyncio
import os
from wukong_easy_sdk import AuthOptions, WKIM, WKIMChannelType, WKIMEvent


async def main():
    im = WKIM.init(
        os.environ.get("WKIM_URL", "ws://127.0.0.1:5200"),
        AuthOptions(uid="alice", token=os.environ["WKIM_TOKEN"]),
    )

    def on_message(message):
        # 将 message["payload"] 交给应用 UI 或有界队列，不记录完整消息。
        pass

    listener = im.on(WKIMEvent.MESSAGE, on_message)
    im.on(WKIMEvent.ERROR, lambda error: print("EasySDK operation failed"))
    async with im:
        ack = await im.send("bob", WKIMChannelType.PERSON, {"type": 1, "content": "你好，Python！"})
        assert ack["reasonCode"] == 1
        await asyncio.sleep(10)
    im.off(WKIMEvent.MESSAGE, listener)


asyncio.run(main())
```

Bob 必须已在线。两个终端分别设置 `WKIM_UID`、`WKIM_TOKEN`、`WKIM_PEER`，运行
`python examples/chat.py` 即可交互收发，输入 `/quit` 退出。示例主动展示消息内容；
不要将终端输出直接接入生产日志采集。

## 使用约定

- `async with im` 在进入时完成鉴权，退出时调用 `destroy()`；也可显式
  `await connect()`、`await disconnect()`、`await destroy()`。
- 每个实例只属于一个 asyncio 事件循环，没有全局单例；更换账号或 Token 时关闭旧实例。
- 并发 `connect()` 共享一次连接；取消某个等待者不会取消其他等待者，显式断开才停止连接。
- 同步或异步事件回调在独立分发任务中串行执行，可在异步回调中 `await im.send(...)`、
  `await im.disconnect()` 或 `await im.destroy()`。不要阻塞事件循环，也不要等待同一串行
  分发器上的后续事件。`on` 返回原回调，保存后用 `off(event, callback)` 移除。
- Python 参数采用 snake_case，消息和结果字典保留 JS 的 camelCase 字段。
  `messageId` 为字符串，`messageSeq` 保持 64 位整数精度，消息 `timestamp` 为秒。
- `send()` 支持 `client_msg_no`、`header`、`setting`、`topic`；Payload 是 JSON 对象
  或数组，按 UTF-8 JSON 编码为 Base64；接收兼容对象、JSON 文本与 Base64 JSON。
  `redDot` 默认 true，显式 false 会保留。群聊使用 `WKIMChannelType.GROUP`，成员关系由后端维护。
- 事件包括 `CONNECT`、`DISCONNECT`、`MESSAGE`、`ERROR`、`SEND_ACK`、`RECONNECTING`、
  `CUSTOM_EVENT`。自定义事件包含 `id`、`type`、毫秒级 `timestamp` 和 `data`。
- `WKIMError.code` 保留服务端原因码或本地 `ErrorCode`，错误文本不包含服务端敏感内容。

## 超时、容量与安全

默认连接总超时 10 秒，请求 15 秒，心跳间隔 25 秒，Pong 超时 10 秒，关闭超时 2 秒。
同 ID 的 `result: null` 可确认心跳。成功鉴权后意外断线最多重试 5 次，从 1 秒指数退避，
最多 30 秒，附带 20% 抖动。首次连接失败、鉴权拒绝、服务端主动断开、协议错误、事件队列满、
证书校验失败和手动退出不自动重试。

默认 1,024 个待处理请求、4 MiB 序列化请求、1 MiB 单条线路消息；事件队列最多 256 条，
线路大小预算 4 MiB，包含正在处理的事件，Python 对象开销另计。WebSocket 接收缓冲上限为
16 帧，写缓冲高水位为 32 KiB。请求满返回 `QUEUE_FULL`；事件队列满关闭连接，未进入队列
的消息不会被确认。过载时生命周期事件为尽力投递。回调应保持短小，并由应用控制处理速度。

RECVACK 在消息进入队列后发送，表示传输接收，不代表业务完成或已读。SDK 不自动重发，
不提供离线队列、会话、未读、历史同步、订阅或推送。超时或断线后 SEND 是否提交可能未知，
请保留 `client_msg_no` 通过后端对账，按业务要求去重。

WSS 默认验证证书链和主机名，最低 TLS 1.2；私有 CA 使用
`WKIMOptions(ca_file="/path/ca.pem")`，示例读取 `WKIM_CA_FILE`，不提供跳过校验选项。
SDK 不读取系统代理，直接使用传入的 Gateway/代理 URL。

默认静默；`WKIMOptions(debug_logging=True)` 只启用固定生命周期元数据，SDK 不输出
Token、Payload、URL、原始帧、服务端响应文本或底层异常对象。

## 开发验证

```sh
uv sync --locked
uv run pytest
uv run pytest -m integration
uv run ruff check .
uv run mypy
uv build
uv run python tests/product.py --server /absolute/path/to/wukongim \
  --js-entry /absolute/path/to/WuKongEasySDK-JS/dist/cjs/index.js
```

完整环境与范围见[验证记录](docs/VALIDATION.md)，接口迁移见[JS 对照表](docs/API.md)。
