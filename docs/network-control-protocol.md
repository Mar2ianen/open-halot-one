# CL-60 WebSocket control protocol

This page documents the vendor WebSocket service used by `PrinterUI`, separately from the Linux-to-STM32 UART protocol in [protocols.md](protocols.md). Findings come from the ARM library copied from this printer and static call-path analysis. No status, pause, stop, upload, or print command was sent to the live service as part of this analysis.

## Listener and transport

The running `PrinterUI` process has a listener on TCP port `18188`. The latest runtime listing showed `:::18188` (IPv6 wildcard); IPv4 dual-stack behavior was not tested. The local listener address is omitted here.

The private copy of `/usr/lib/libcxWebsocket.so` is an ARM ELF32 shared library, 173,404 bytes, SHA-256 `47cd9804209c56a704e151f8a2c76db0957e1dca83200d15b3f463cf319e8a23`. The library is not redistributed in this repository.

Despite the class name `CxSslEchoServer`, its constructor at `0x1374c` constructs `QWebSocketServer` with `SslMode` value `1`. The target Qt 5 API assigns `1` to `NonSecureMode` (`ws://`) and `0` to `SecureMode` (`wss://`); the constructor separately creates an SSL configuration, but Qt documents that SSL configuration has no effect in non-secure mode. This is therefore a plain WebSocket service, not TLS. See the [Qt 5 QWebSocketServer reference](https://doc.qt.io/qt-5/qwebsocketserver.html).

`processTextMessage(QString)` at `0x144c4` converts the text to UTF-8 and `messageToJson(QString)` at `0x151a0` accepts only a JSON object. The server matches the sending socket to its `CxWebHandle` and dispatches the object to that connection's handler. It also has separate WebSocket binary-message/frame callbacks; file payload framing and resume semantics are not fully recovered yet.

## Text command vocabulary

`CxFileTransHandle::processJson(QJsonObject)` at `0x19b8c` reads the top-level string key `cmd` and compares it to the `TRANSCMD` Qt enum names. The enum values and names recovered from the library are:

| Value | `cmd` | Handler / current finding |
|---:|---|---|
| 0 | `TRANSCMD_NULL` | Null/default enum value |
| 1 | `START_FILE` | Enters `startFile(QJsonObject)` |
| 2 | `CANCEL_FILE` | Enters `cancelFile(QJsonObject)` |
| 3 | `START_DATA` | Present in the enum; data-frame relationship still needs tracing |
| 4 | `CHECK_DATA` | Present in the enum; data-frame relationship still needs tracing |
| 5 | `START_PRINT` | Enters `startPrint(QJsonObject)` |
| 6 | `PRINT_PAUSE` | Enters `printPause(QJsonObject)` |
| 7 | `PRINT_STOP` | Enters `printStop(QJsonObject)` |
| 8 | `GET_PRINT_STATUS` | Enters `getPrintStatus(QJsonObject)` |
| 9 | `VERSION_CHECK` | Enters `verSionCheck(QJsonObject)` |
| 10 | `PRINT_PARA_SET` | Enters `setPrintPara(QJsonObject)` |

The listed command words are binary-confirmed CL-60 network commands, not STM32 UART commands. `START_DATA` and `CHECK_DATA` also occur in the file-transfer enum and logs, but their relationship to the binary WebSocket callbacks and exact payload sequence is not yet completely established.

The library's JSON field strings include `cmd`, `filename`, `size`, `offset`, `token`, `errorcode`, `compress`, `received`, and `checkstate`. The status reply path additionally uses `status`, `printStatus`, `sliceLayerCount`, `curSliceLayer`, `printRemainTime`, `initExposure`, `delayLight`, `printExposure`, `printHeight`, `eleSpeed`, `bottomExposureNum`, `layerThickness`, and `resin`. The field inventory is recovered; not every field's role in every command has been traced.

## Status request, authentication, and reply

`GET_PRINT_STATUS` reads a top-level `token` string and passes it to `CxSslEchoServer::getPrinterStatus`, which emits `sigGetPrinterStatus(PrintStatusPara&, QString)`. `PrinterUI`'s slot calls `WebsocketTransFile::checkToken(QString)`. That function compares the supplied string with `Cencrypt::getEncryptData()`; `Cencrypt::doEncrypt(QString)` converts its input to UTF-8 and calls the binary's `des_encrypt_str` routine. A rejected token sets the print-state result to `TOKEN_ERROR` (state value 8). The exact configured source text and whether a third-party token generator uses the same DES key/input recipe remain unverified; secrets are intentionally not included here.

For a valid status request, `getPrintStatus(QJsonObject)` builds and sends a JSON text object with `cmd: "GET_PRINT_STATUS"`, a string-valued `printStatus`, and these string-valued fields copied from `PrintStatusPara`:

```json
{
  "cmd": "GET_PRINT_STATUS",
  "printStatus": "PRINT_PROCESSING",
  "sliceLayerCount": "…",
  "curSliceLayer": "…",
  "printRemainTime": "…",
  "initExposure": "…",
  "delayLight": "…",
  "printExposure": "…",
  "printHeight": "…",
  "eleSpeed": "…",
  "bottomExposureNum": "…",
  "layerThickness": "…",
  "resin": "…"
}
```

The code constructs JSON strings for these fields; clients should not assume that their wire types are JSON numbers. The state labels returned by `getPrintStatusKey(int)` are:

| Value | State label |
|---:|---|
| 0 | `PRINT_GENERAL` |
| 1 | `PRINT_PROCESSING` |
| 2 | `PRINT_COMPLETE` |
| 3 | `PRINT_FAIL` |
| 4 | `PRINT_END` |
| 5 | `PRINT_STOP` |
| 6 | `PRINT_STOPING` |
| 7 | `PRINT_COMPLETING` |
| 8 | `TOKEN_ERROR` |

The recovered status reply builder does not add `filename` or `progress`. It does include the current layer, total layer count, and remaining time. This is a concrete schema difference from clients that expect those omitted fields.

## Comparison with Creality-Control / Halot Box clients

Creality-Control's public Home Assistant [status source](https://github.com/SiloCityLabs/Creality-Control/blob/main/custom_components/creality_control/__init__.py) opens `ws://host:18188/`, sends `GET_PRINT_STATUS` with a token, and expects `printStatus`, `filename`, `printRemainTime`, `progress`, `curSliceLayer`, and `sliceLayerCount`. Its [pause/stop buttons](https://github.com/SiloCityLabs/Creality-Control/blob/main/custom_components/creality_control/button.py) use the same `PRINT_PAUSE` and `PRINT_STOP` words. Those command names and several status fields now match the CL-60 binary, so this is stronger evidence than the previously known shared port alone.

This remains partial protocol overlap, not a completed compatibility result. The CL-60 status response lacks `filename` and `progress`; the Home Assistant DES token recipe has not been checked against the value produced by this printer's `Cencrypt`; and no live WebSocket request/response has been captured. The public compatibility tracker still has no completed model-specific HALOT-ONE test. A passive handshake or a read-only status request with an independently verified token would close the remaining status-path questions; pause/stop and print-start behavior require a separate controlled check.

## Static function map

| Function | Address | Recovered role |
|---|---:|---|
| `CxSslEchoServer::CxSslEchoServer(...)` | `0x1374c` | Constructs non-secure WebSocket server (`SslMode=1`) |
| `CxSslEchoServer::processTextMessage(QString)` | `0x144c4` | Maps text message to the owning socket handler |
| `CxSslEchoServer::messageToJson(QString) const` | `0x151a0` | UTF-8 JSON-object parser |
| `CxFileTransHandle::processJson(QJsonObject)` | `0x19b8c` | `cmd` enum dispatch |
| `CxFileTransHandle::getPrintStatus(QJsonObject)` | `0x1c9a4` | Token-bearing status request and reply construction |
| `CxFileTransHandle::printPause(QJsonObject)` | `0x1c334` | Pause command handler |
| `CxFileTransHandle::printStop(QJsonObject)` | `0x1c66c` | Stop command handler |
| `CxFileTransHandle::getPrintStatusKey(int)` | `0x1e400` | Print-state enum to string mapping |

## References

- [Qt 5.15 `QWebSocketServer` reference](https://doc.qt.io/qt-5/qwebsocketserver.html) — documents the `SecureMode`/`NonSecureMode` enum and WebSocket URL schemes.
- [Creality-Control status implementation](https://github.com/SiloCityLabs/Creality-Control/blob/main/custom_components/creality_control/__init__.py), [sensors](https://github.com/SiloCityLabs/Creality-Control/blob/main/custom_components/creality_control/sensor.py), and [buttons](https://github.com/SiloCityLabs/Creality-Control/blob/main/custom_components/creality_control/button.py).
- [Creality-Control compatibility tracker](https://github.com/SiloCityLabs/Creality-Control/issues/1).
