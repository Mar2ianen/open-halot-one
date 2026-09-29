# PrinterUI binary analysis

## Binary and method

`PrinterUI` was copied from the running unit without modifying it. It is an ELF32 little-endian ARM EABI5 hard-float executable with Qt 5, OpenCV 3.3, FFmpeg 3.x, `libcxdlp.so`, `libcxWebsocket.so`, `libnettrans.so`, and `libwifimg.so` dependencies. It is stripped, but contains enough C++ symbols, class names, log messages, and file-format strings to recover major call paths.

Ghidra 12.1.4 imported the binary and completed auto-analysis. A script exported decompilation for 723 functions referenced by strings related to printing, image output, serial I/O, motion, networking, and firmware update. This is static analysis; commands were not sent to the printer from the host.

## Main control path

| Function | Ghidra entry | Observed role |
|---|---:|---|
| `MainView::InitSerialPort` | `0x0023b8d4` | Builds the configured port path and creates `CXSerial` with baud argument `0x1c200` (115,200). |
| `Controller::checkDev_ttyUSB0` | `0x00164a40` | Checks whether the USB serial device name `ttyUSB0` is available. |
| `SerialPortPrintFile::lcdPrint` | `0x00274d64` | Active CL60 LCD layer loop. |
| `SerialPortPrintFile::dlpPrintCxline` | `0x0027d8f4` | Layer print loop for CXLINE jobs. |
| `SerialPortPrintFile::doExposure` | `0x0027c874` | DLP-oriented path: sends a status query, opens the light after a reply, and polls the DLP backend status. |
| `SerialPortPrintFile::getMotorMoveUpCommand` | `0x00280250` | Builds a motion command from the active machine parameters. |
| `SerialPortPrintFile::getMotorMoveDownCommand` | `0x00280798` | Builds the corresponding downward-motion command. |

At runtime PrinterUI held `/dev/ttyS2` open; the device tree maps this to Allwinner UART2 at `0x05000800`. The startup updater also selects `/dev/ttyS2` and controls the MCU's BOOT0/reset entry sequence. Separately, static disassembly of the STM32 application ties its command mailbox to MCU USART1 RX. Together these make H616 UART2 to STM32 USART1 the likely application path, while the physical cable, voltage, connector, and pin mapping remain unverified. The binary also contains a `ttyUSB0` detection branch, but no such node was present at inspection time. Baud and framing settings are recovered statically and from live `stty`.

The active CL60 `lcdPrint` loop waits until the parser has produced layer *i*, submits it through `SendBgraImage`, then sends its prepared `M678` command over UART. It increments the layer index and starts parsing layer *i+1* before it waits for the current serial/M114 cycle; the next frame is not submitted until `M114_OK` completes and the next loop iteration begins. It then calls `WaitMotorStatus` before advancing. With its polling flag clear, the helper sends framed `M114` queries about every 220 ms. `CXSerial::getRecvTypeAndMsg` splits the raw line on `_`, making `M114_OK` map to key `M114` and value `OK\n`; `waitRecvMsgFromSerial` returns that value, which `WaitMotorStatus` accepts by an exact comparison with `OK\n`. The live log records `strCmd M114` and `strMsg "OK\n"`, followed by the helper's end marker. The completed post-print trace records all 1,591 M678 layer cycles; each is followed by M678_Busy, M114_DELATLIGHT_OVER, and M114_OK before the next layer. The stock log reaches 100% and layer 1591/1591. `WaitMotorStatus` does not call `doExposure`, `waitExposureResult`, or `waitExposureEnd`. Separate DLP/CXLINE print workflows use a different ordering and call the DLP-oriented exposure helpers. In all cases, the bitmap travels through the display path rather than inside the UART frame.

The DLP-specific `doExposure` path sends an `M114` query, waits for its matching response, and calls `openLight` (`M42 P36 M1 S0`). The STM32 state-7 worker path sets an event bit that its M114 handler can return once as `M114_DELATLIGHT_OVER`. CL60 queries M114 through `WaitMotorStatus` but does not call `openLight` in the LCD loop; its `M114_OK` response is parsed as map value `OK\n`, the exact string accepted by the host helper. The STM32 worker's internal phase timing and the point where the display path gates it remain unresolved. Likewise, `waitExposureResult` (`0x0027e6f4`) and `waitExposureEnd` (`0x001c0248`) are called from DLP workflows, not the normal CL60 layer loop. `YuvDataSend::waitExposureFinished` (`0x00211f64`) always loads DLP handle `0x47ad58`; DLP backend slots `+0x1c`/`+0x24` read status and total frames, while the generic Video backend is held separately at `0x47ad38`. Its status getter reads the DLP driver's `dlp_status` sysfs attribute. CL60's profile takes the Video factory, so it does not initialize the DLP handle during normal startup. Calling `waitExposureFinished` after only Video initialization would dereference a null or stale DLP handle; the ordinary CL60 loop does not make that call. The DLP wrapper polls about every 220 ms while status is 4, retries once after a one-second delay for status 2, and accepts 5 as success. Those codes are DLP-backend results; their physical meaning and any relationship to panel VSYNC are not established. See the STM32 [protocol map](protocols.md).

The print loop also uses motion templates such as `G0 Z500 F… D1 S1/S0 H…` (up) and `G0 Z… F… D0 S1/S0 H…` (down). The bitmap's physical panel timing and the exact condition that gates each MCU phase remain unresolved.

## Exposure-image path

The executable distinguishes `.cxdlp` and `.cxline` processing. `parseOnePictureFromCxdlp` (`0x0027d4e4`) and `parseOnePictureFromCxline` (`0x0027d6ec`) start or stop the asynchronous layer parser. The linked CXDLP reader and CXLINE v2 wrapper expose header, image-parameter, layer-path, and checksum functions.

`SerialPortPrintFile` uses `SendBgraImage` to submit a parsed layer. The `YuvDataSend` class has a dedicated `CreatevDlpOutport` initialization path and a `CreateVideoOutport` alternative. `sendImageDataToDlp` copies a `QImage` pixel buffer and submits it through the selected output object, retrying failed submissions. Other methods enable/disable the display output port, control light intensity, and wait for exposure completion.

For the active CL60 profile, `halotMachine.xml` selects the generic `CreateVideoOutport` path rather than the model-dependent `CreatevDlpOutport` branch. It records source 1620×2560, compressed output 540×2560, and `RgbRange=BGRA`. In `writerClearImage`, output coordinate `(x,y)` reads source bytes at `y*1620 + 3*x` through `+2`; for BGRA it writes those three values in reverse byte order followed by `0xff`. This packs three one-byte layer samples into one four-byte output pixel. The converted 5,529,600-byte frame is copied into one external ION display buffer and submitted by layer configuration through `/dev/disp` ioctl `0x47`; the active descriptor and driver calculation establish a dense 2,160-byte row pitch. PrinterUI sets z-order 1 and enables the layer; the active call path does not alternate buffers. The live kernel log shows the matching 540×2560 HDMI input and 4×840 Mb/s DSI1 link. Static RK628 profile tracing selects `panel_cmd_init_seq_tm89`; the separate type-1 timing lookup selects `dst_mode_boe_5_96` at 540×2560/112 MHz. The runtime timing override could not be read. The final RGB-to-monochrome column mapping and application point of `MirroredX=true` remain unresolved. This path is separate from the 800×480 `/dev/fb0` operator GUI. See [the display data path](display-pipeline.md).

The printer's product documentation identifies the exposure panel as a monochrome LCD. The DLP-named outport function is only a software/backend name; it does not mean the optical panel is DLP. The I²C0 `cxsw,dlp1438` node is not the active route on this CL60: its driver probe logs `device not the CD60` and exits with `-22`. The remaining unverified details are the bridge's exact RGB-to-monochrome pixel mapping and the physical DSI1-to-panel FPC trace.

## Other software paths

- MQTT async, WebSocket, `CXYManager`, upload/download, and firmware-update functions are present. Embedded build strings identify a candidate `cxpm2-2.303.1` application build.
- A runtime listing on 2026-09-29 showed `PrinterUI` listening on TCP `:::18188`; IPv4 dual-stack behavior was not checked. The `libcxWebsocket.so` service and its statically recovered JSON API are documented in [network-control-protocol.md](network-control-protocol.md).
- The process opened `/dev/disp`, `/dev/ion`, `/dev/mali0`, `/dev/fb0`, and touch input. This matches the Qt GUI and the separate image-output backend.
- The binary clone, Ghidra database, decompiler pseudocode, function index, and string-reference listing are retained in the owner's private local output archive. Vendor code is not committed to this repository.

## Limits and next evidence

The Ghidra output recovers call structure, but some strings and configuration values are built through relocations and the linked serial/output library bodies are not included in this executable. To identify the exact STM32 chip, UART pins, panel FPC, and signal direction, the printer-control board and cable routing would need physical inspection. The owner has not opened the printer, so those items remain explicitly unconfirmed.
