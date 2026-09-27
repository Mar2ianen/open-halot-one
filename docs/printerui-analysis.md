# PrinterUI binary analysis

## Binary and method

`PrinterUI` was copied from the running unit without modifying it. It is an ELF32 little-endian ARM EABI5 hard-float executable with Qt 5, OpenCV 3.3, FFmpeg 3.x, `libcxdlp.so`, `libcxWebsocket.so`, `libnettrans.so`, and `libwifimg.so` dependencies. It is stripped, but contains enough C++ symbols, class names, log messages, and file-format strings to recover major call paths.

Ghidra 12.1.4 imported the binary and completed auto-analysis. A script exported decompilation for 723 functions referenced by strings related to printing, image output, serial I/O, motion, networking, and firmware update. This is static analysis; commands were not sent to the printer from the host.

## Main control path

| Function | Ghidra entry | Observed role |
|---|---:|---|
| `MainView::InitSerialPort` | `0x0023b8d4` | Builds the configured port path and creates `CXSerial` with baud argument `0x1c200` (115,200). |
| `Controller::checkDev_ttyUSB0` | `0x00164a40` | Checks whether the USB serial device name `ttyUSB0` is available. |
| `SerialPortPrintFile::lcdPrint` | `0x00274d64` | Layer print loop for the LCD/DLP print path. |
| `SerialPortPrintFile::dlpPrintCxline` | `0x0027d8f4` | Layer print loop for CXLINE jobs. |
| `SerialPortPrintFile::doExposure` | `0x0027c874` | Sends the exposure-start serial command, waits for a reply, opens the light, and polls exposure status. |
| `SerialPortPrintFile::getMotorMoveUpCommand` | `0x00280250` | Builds a motion command from the active machine parameters. |
| `SerialPortPrintFile::getMotorMoveDownCommand` | `0x00280798` | Builds the corresponding downward-motion command. |

At runtime PrinterUI held `/dev/ttyS2` open; the device tree maps this to Allwinner UART2 at `0x05000800`. The bundle's startup updater also selects `/dev/ttyS2` and controls the MCU's BOOT0/reset entry sequence, confirming that UART2 is the control-board path at the software level. The binary also contains a `ttyUSB0` detection branch, but no such node was present at inspection time. Baud and framing settings are recovered statically and from live `stty`; the physical cable destination, voltage levels, connector, and STM32 pins remain unverified.

The print loop homes and moves the Z platform, requests the next layer, sends a serial command, waits for serial/motor state, sends image data, performs the exposure delay, and advances the layer/progress state. `doExposure` accepts one reported status as success and treats another as failure; the full status enumeration is not recovered. Static strings and call sites identify motion templates such as `G0 Z500 F… D1 S1/S0 H…` (up) and `G0 Z… F… D0 S1/S0 H…` (down). See [the protocol map](protocols.md) for the recovered frame layout and command families.

## Exposure-image path

The executable distinguishes `.cxdlp` and `.cxline` processing. `parseOnePictureFromCxdlp` (`0x0027d4e4`) and `parseOnePictureFromCxline` (`0x0027d6ec`) start or stop the asynchronous layer parser. The linked CXDLP reader and CXLINE v2 wrapper expose header, image-parameter, layer-path, and checksum functions.

`SerialPortPrintFile` uses `SendBgraImage` to submit a parsed layer. The `YuvDataSend` class has a dedicated `CreatevDlpOutport` initialization path and a `CreateVideoOutport` alternative. `sendImageDataToDlp` copies a `QImage` pixel buffer and submits it through the selected output object, retrying failed submissions. Other methods enable/disable the display output port, control light intensity, and wait for exposure completion.

For the active CL60 profile, `halotMachine.xml` selects the generic `CreateVideoOutport` path rather than the model-dependent `CreatevDlpOutport` branch. `writerClearImage` reduces the 1620-pixel source width to 540 pixels before output; the frame is placed in an ION buffer and submitted through the `/dev/disp` display-layer API. Live kernel logs then show the matching 540×2560 signal arriving at the RK628 HDMI receiver, followed by successful DSI1 initialization at 840 Mb/s on four lanes. This correlates the PrinterUI layer path with the exposure display link at high confidence. The active path is distinct from the 800×480 `/dev/fb0` operator GUI.

The printer's product documentation identifies the exposure panel as a monochrome LCD. The DLP-named outport function is only a software/backend name; it does not mean the optical panel is DLP. The I²C0 `cxsw,dlp1438` node is not the active route on this CL60: its driver probe logs `device not the CD60` and exits with `-22`. The remaining unverified details are the bridge's exact RGB-to-monochrome pixel mapping and the physical DSI1-to-panel FPC trace.

## Other software paths

- MQTT async, WebSocket, `CXYManager`, upload/download, and firmware-update functions are present. Embedded build strings identify a candidate `cxpm2-2.303.1` application build.
- `PrinterUI` listened on TCP port `18188` at a specific local address during the runtime inspection. Its local address is intentionally excluded from this public project.
- The process opened `/dev/disp`, `/dev/ion`, `/dev/mali0`, `/dev/fb0`, and touch input. This matches the Qt GUI and the separate image-output backend.
- The binary clone, Ghidra database, decompiler pseudocode, function index, and string-reference listing are retained in the owner's private local output archive. Vendor code is not committed to this repository.

## Limits and next evidence

The Ghidra output recovers call structure, but some strings and configuration values are built through relocations and the linked serial/output library bodies are not included in this executable. To identify the exact STM32 chip, UART pins, panel FPC, and signal direction, the printer-control board and cable routing would need physical inspection. The owner has not opened the printer, so those items remain explicitly unconfirmed.
