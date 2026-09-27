# Protocol map

This page separates the Linux-to-controller serial protocol, the STM32 application commands, and the STM32 ROM programming protocol. Findings below come from the running Linux process, the PrinterUI decompilation, and the firmware shipped in the downloaded update. We have one syscall-level PrinterUI startup trace, but no independent electrical UART capture; we did not reset the MCU into ROM mode or send test commands.

## Linux UART to printer controller

| Property | Finding | Evidence |
|---|---|---|
| Linux device | `/dev/ttyS2` | Open by the live `PrinterUI` process; selected by the startup STM32 updater for this product |
| SoC controller | Allwinner UART2 at `0x05000800` | Flattened device tree and sysfs |
| Application baud | 115,200 baud | `MainView::InitSerialPort` argument and live `stty` state |
| Frame parameters | 8 data bits, no parity, 1 stop bit, no hardware/software flow control | Live `stty` state and `CXSerial` constructor |
| STM32 application UART | USART1, configured for 115,200 baud; command input is DMA RX and reply bytes use polled TX | The main task consumes the USART1 RX mailbox; the formatter's byte callback at `0x080044f4` waits for USART1 `SR.TXE` (`0x40`) and writes each byte to `USART1.DR` (`0x40013804`) |
| Physical endpoint | The update script and PrinterUI both use Linux `/dev/ttyS2`; this strongly suggests it reaches the MCU application UART, but the board trace, connector, STM32 pins, voltage, and wire direction remain unverified | Linux runtime/script evidence plus MCU firmware disassembly; no board photo or electrical capture |

The `CD60` and `D160` product branches select `/dev/ttyS3`; the other branch selects `/dev/ttyS2`. The inspected unit reports `CL60`.

### STM32 UART and DMA setup recovered in Renode

The raw application image was run in Renode against its STM32F103 platform with a deliberately minimal RCC stub. CPU writes to the STM32F1 register map configure:

| MCU peripheral | Firmware configuration observed | Interpretation |
|---|---|---|
| USART1 RX | DMA1 channel 5; `CPAR=0x40013804`, `CMAR=0x20000578`, `CNDTR=0xc8`, then channel enable | 200-byte peripheral-to-memory receive buffer |
| USART2 RX | USART2 CR3 `DMAR` set; DMA1 channel 6; `CPAR=0x40004404`, `CMAR=0x200007d0`, `CNDTR=0xc8`, then channel enable | 200-byte peripheral-to-memory receive buffer |
| USART2 TX | USART2 CR3 `DMAT` set; DMA1 channel 7 points at `0x40004404` and RAM buffer `0x20000640`; initial transfer count is zero | Memory-to-peripheral transmit path, likely armed when a reply is sent |
| USART3 TX | DMA1 channel 2; `CPAR=0x40004804`, `CMAR=0x20000898`; initial transfer count is zero | Auxiliary serial output, armed for each transfer |
| USART3 RX | DMA1 channel 3; `CPAR=0x40004804`, `CMAR=0x20000a28`, `CNDTR=0xc8`, then channel enable | 200-byte auxiliary serial receive buffer |

The DMA channel mappings and register addresses are consistent with an STM32F1-style peripheral map. Linux `/dev/ttyS2` identifies Allwinner UART2. Static disassembly ties the command parser to **USART1 RX** and the response formatter to **USART1 TX**; USART2 has separate RX/TX DMA setup, and USART3 has a separate RX DMA setup. The likely host-to-MCU path is H616 UART2 (`/dev/ttyS2`) to STM32 USART1, although the exact PCB routing remains unverified. Renode recovered peripheral configuration only: DMA was a memory-backed stub, so it produced no UART bytes or protocol transcript and provides no transfer-timing evidence. Renode's [STM32F103 platform](https://github.com/renode/renode/blob/master/platforms/cpus/stm32f103.repl) is a base rather than a full model of the exact Creality MCU; missing blocks can be added using its [Python peripheral mechanism](https://renode.readthedocs.io/en/latest/basic/using-python.html).

### STM32 receive framing and interrupt path from static disassembly

This path was recovered directly from `V1-01.bin`, not from Renode's nonfunctional DMA stub:

1. STM32 USART1 uses DMA1 channel 5 with a 200-byte RX area at `0x20000578`. On USART1 IDLE, the handler at `0x08003078` tests USART `CR1.IDLEIE` and `SR.IDLE` (helper at `0x080033f8`, encoded selector `0x424`), then reads the data register via `0x08003570`. It disables DMA, samples `CNDTR`, reloads the 200-byte transfer and buffer address, copies `200 - CNDTR` received bytes to `0x200004b0`, and reenables DMA.
2. A separate consumer task at `0x08006ddc` reads the mailbox at `0x200004b0`. It dispatches the command only when byte offset `0x63` (decimal 99) equals `0x55` (`'U'`), then calls the command dispatcher at `0x08005510`.
3. The dispatcher tokenizes the first 100 bytes with `0x080041f0`: up to nine space-separated ten-byte slots. Thus the four `0x55` bytes at offsets 96–99 in PrinterUI's fixed body act as a frame marker; the active STM32 gate checks the last one. The LF sent by PrinterUI is byte 100, after the checked 100-byte body.

This closes the software-side receive framing: command payload, fixed `0x55` trailer, marker position, IDLE-triggered DMA handoff, and dispatcher entry point are all visible in the shipped MCU image. It does not establish electrical pin mapping or prove how fragmented frames across multiple IDLE gaps are handled. The separate `parserSerialMsg` checksum routine still has no active call path identified.

Before the normal mailbox consumer checks byte 99 for the `0x55` frame marker, the USART1 IDLE handler searches its 200-byte mailbox for raw ASCII substrings. A `reboot` match emits `OK\n` and requests a Cortex-M system reset. Otherwise, a `test` match emits `test ok\n`. These are unframed ISR-level exceptions; neither string was sent during this analysis. The normal PrinterUI startup trace contains only `V114` and `MODELS:A`.

The IDLE handler copies only the number of bytes received into the mailbox; the reviewed path does not clear the remaining mailbox bytes or append a terminator before these substring searches. The normal consumer likewise gates on mailbox byte 99, so a short IDLE fragment can leave an old `0x55` marker there. This is a static parser edge case, not a demonstrated live failure: whether it can affect a real session depends on UART gap timing, fragment lengths, and task scheduling. It also means stale bytes could satisfy the raw substring checks after a later short receive. No malformed or short frame was injected to test this behavior.

The other IRQs are distinct: USART2 uses DMA1 channel 6 for RX and channel 7 for TX; USART3 uses DMA1 channel 3 for RX and channel 2 for TX. The vector table points USART1/2/3 IRQs to handlers at `0x08003078`, `0x080031a0`, and `0x0800321c`; DMA1 channel7 has a custom handler at `0x08001252`, while channel5/6 vectors point to the default handler. USART2/3 are auxiliary paths; their relation to product-specific controllers is described below.

### Auxiliary USART2/USART3 paths

The STM32 image configures two extra bidirectional UARTs in addition to the main USART1 control link. USART2 uses DMA1 channel 6 for 200-byte RX and channel 7 for TX through staging buffer `0x20000640`; its model-B startup branch sets 115,200 baud. USART3 uses DMA1 channel 3 for 200-byte RX and channel 2 for TX through `0x20000898`; its model-C/D startup branches set 9,600 baud, and model G sets 115,200 baud. These mode letters are firmware configuration selectors; the physical endpoints are not identified from the available evidence.

On USART2/3 IDLE, the firmware copies the received DMA bytes to a scratch buffer, rearms and clears the RX buffer, then writes the received text to USART1 using the formatter `%s\n`. USART3's handler can also set event bit 0 in the object at `0x20000030` (except in mode G). Thus auxiliary replies can appear as ordinary lines on the main host UART, without a protocol prefix that identifies which auxiliary UART produced them.

The only proven firmware model selector is the character at `0x20000000`. When that field is invalid, startup waits for a `MODELS:` message and copies its byte at offset 7 into the selector; the captured handshake `MODELS:A` therefore selects mode A. The STM32 accepts letters A through G and formats a `GET MODELS:%s OK\n` reply. This wire/runtime selector is separate from the active XML profile's `SendSerialModelType=E`; those values are not the same setting. Address `0x20000138` is a 3-byte send buffer used by the `M106 P2 S00` path, not a second model selector.

Static startup routing recovered from the model comparisons is:

| STM32 mode | Startup route |
|---|---|
| A | Generic helper `FUN_080045c6` |
| B | USART2 at 115,200 baud |
| C | USART3 at 9,600 baud; waits 1 second, then runs the seven-stage `M800` exchange |
| D | USART3 at 9,600 baud; runs the seven-stage `M800` exchange, then waits 3 seconds |
| E | Generic helper `FUN_080045c6`, then an additional helper `FUN_080025c4` |
| F | Generic helper `FUN_080045c6` |
| G | USART3 at 115,200 baud |

The model-dependent auxiliary routes are firmware branches; the physical connector or accessory served by each one is not identified. The Linux PrinterUI binary contains command-template strings for `M355`, `M106 P1 S0`, `M107 P1 S0`, and `M410 S0/S1/S2`. It contains no `M800` command string, consistent with the seven-stage exchange being a controller-side startup/accessory routine. The available static call-path export does not establish an active PrinterUI call order for the `M355` strings.

## Control UART versus layer-image path

The UART is the STM32 control/status channel: it carries the ASCII-like commands and line replies described below. CL60 layer bitmaps use a separate H616 video-output path. The active `CL60` profile in `halotMachine.xml` selects `CreateVideoOutport`, source dimensions 1620×2560, compressed dimensions 540×2560, and `RgbRange=BGRA`. Static analysis of `writerClearImage` shows each output pixel is built from three consecutive source samples and an opaque alpha byte. The running kernel shows the 540×2560 mode entering the RK628 HDMI receiver before MIPI DSI1. Thus the large exposure bitmap is not framed into the 100-byte UART command protocol. The software-side pixel packing is recovered; the exact downstream RK628/DSI mapping to panel columns remains open. See [the display data path](display-pipeline.md).

### PrinterUI layer and exposure synchronization

The active CL60 `SerialPortPrintFile::lcdPrint` path prepares the per-layer `M678`, waits for the asynchronous file parser, submits the image through `SendBgraImage`, then sends the command over the control UART. It waits for the matching UART reply and calls `WaitMotorStatus` before advancing to the next layer. With its polling flag clear, `WaitMotorStatus` repeats about every 220 ms: it sends framed `M114`, clears RX, and waits for a response keyed as `M114`; it accepts only the returned string `M114 ` byte-for-byte, including its trailing space. The STM32's known replies (`M114_OK`, `M114_OK1`, `M114_Busy`, `M114_Busy_n`, and `M114_DELATLIGHT_OVER`) all parse to payloads that fail that exact host-side match. This is an apparent static host/firmware response mismatch; its runtime consequence is unknown without a layer trace. The pause-related flag can take a different branch. `lcdPrint` does not call `doExposure`, `waitExposureResult`, or `waitExposureEnd`. Separate DLP/CXLINE workflows use different orderings and the DLP-oriented exposure helpers. These are function-specific paths recovered from PrinterUI; none embeds the bitmap in the serial frame.

The DLP-specific `doExposure` helper sends `M114` and, after a matching serial response, calls `openLight` (`M42 P36 M1 S0`). DLP print workflows then use `waitExposureResult` (`0x0027e6f4`) → `waitExposureEnd` (`0x001c0248`) → `YuvDataSend::waitExposureFinished` (`0x00211f64`). The final method reads status through the DLP output backend, and the wrapper polls about every 220 ms while the returned status is 4, retries once after a one-second delay for status 2, and accepts status 5 as success. These are DLP-backend results, not CL60 layer-completion or VSYNC results. CL60 initializes the generic Video backend and its ordinary `lcdPrint` call path does not invoke these helpers. The STM32's `M678_Busy` and `M113`/`M114` are MCU state/protocol responses; the precise mapping from MCU worker phases to displayed frame changes remains unresolved. See [PrinterUI's call-path notes](printerui-analysis.md) and [the display data path](display-pipeline.md).

## PrinterUI serial framing

The normal `CXSerial::SendMsgToSerial` path constructs a fixed 100-byte ASCII body and appends line feed (`0x0a`):

| Offset | Bytes | Meaning inferred from code |
|---:|---|---|
| 0–95 | Command bytes, then ASCII spaces (`0x20`) | The caller's final character is dropped before copying; observed command templates commonly end in a trailing space |
| 96–99 | `55 55 55 55` | Fixed trailer |
| 100 | `0a` | Line-feed terminator |

The code computes a 16-bit additive sum over bytes 0–95, but the value is not copied into the outgoing frame. A separate `parserSerialMsg` routine compares such a sum with bytes 0–1 of an input buffer; no call to that routine was found in the active receive call paths examined. Treat the checksum routine as legacy or otherwise unresolved, not as proof that the normal transmitted frame carries a checksum.

The STM32's response formatter emits each byte synchronously: its callback polls USART1 `SR.TXE` and writes `USART1.DR`; command response format strings end in LF. Replies are read with `readline` using LF, with a 100-byte maximum. `getRecvTypeAndMsg` splits reply text on `_`; for example, the firmware contains the format string `M105_TA%0.1f_TB%0.1f`, which yields `M105_TA…_TB…`. PrinterUI maps the first field to the command type and stores the rest as the response associated with that command. No response sequence number or checksum was found in the paths examined.

There is also a `SendMsgMengToSerial` / `RecvMsgMengFromSerial` path. It writes `len(input)+1` bytes (the supplied string plus one LF; no NUL and no 100-byte wrapper) and reads an LF-terminated line, up to 100 bytes. The decompiled `ThreadWorkMengTool` calibration workflow uses it. This is separate from the printer control UART: `SetMengImage::slot_resetClearImge_finish` constructs this serial object for `/dev/ttyUSB0` at 115,200 baud, while `MainView::InitSerialPort` selects the configured control path dynamically (the inspected HALOT profile uses `/dev/ttyS2`). The live device inventory previously had no `/dev/ttyUSB*`, so this calibration endpoint was not present during inspection; the device or accessory it would reach is unknown.

### Vendor MengTool direct-string path

Static decompilation exposes these parts of the separate calibration workflow:

- `ThreadWorkMengTool::waitMotorStatus` writes literal `M114 ` to `/dev/ttyUSB0` through the direct-string API, then polls received text about every 20 ms until it contains `OK` or the calibration stop flag is raised. The STM32's normal application dispatcher only accepts the fixed frame with `0x55` at body offset 99, so this raw `M114` is a different endpoint/protocol from the framed `M114` in `doExposure`.
- `getLightFormSerial` waits 1.3 seconds, clears the serial input, writes `ASK_DATA ` plus LF, and polls for a reply at 20 ms intervals. If parsing fails it resends `ASK_DATA `, and after every five failed reads it clears and requests again. The ELF symbol table retains `ThreadWorkMengTool::recvLightDataDel` at `0x0028e718`, although it was absent from the focused decompilation export: it recognizes `DFront ` or `DBack ` case-insensitively, removes the first 7 or 6 characters respectively, trims the first LF-delimited line, splits on ASCII spaces, and requires at least four fields. `getDataFromString` at `0x002857b4` removes the first character of each field and parses base-10 unsigned integers; the first parsed value is discarded and fields 2–4 are returned as the three measurements. Extra fields and later lines are ignored. The roles/units of these values and the `DFront`/`DBack` distinction are unresolved. The parser uses `contains` rather than a prefix-only test, although it always strips from the start of the string.
- `adjustDownLightIntensity` changes the display backend's intensity, waits 2 seconds, and compares the measured third value returned by `getLightFormSerial` with a target. It adjusts the intensity in steps and stops after 21 iterations or on calibration cancellation. This is a calibration loop, not evidence about normal print exposure timing.
- The receive worker recognizes text markers `LED_ON`, `LED_OFF`, `OK`, `ERROR`, `DFront`, `DBack`, `D`, and `MAX`; it switches light state, parses point/brightness data, or signals completion/error. The `DFront`/`DBack` three-measurement form is now partly recovered above; the remaining `D`/`MAX` record formats and all command variants are unresolved.
- `SetMengImage::slot_calib_stop` writes the raw string `reboot ` plus LF to the MengTool `/dev/ttyUSB0` endpoint, waits 500 ms, then polls for an `OK` response at 20 ms intervals. The STM32 USART1 IDLE handler independently recognizes the same substring and resets the MCU, but the MengTool callsite is bound to `/dev/ttyUSB0`; this does not establish that calibration stop resets the printer's STM32.

The UI's startup calibration flow also sends the ordinary framed `M42 P36 M1 S0` light-enable template and polls for `OK_LED`; this is distinct from the raw `ASK_DATA` exchange. The direct path's selected serial endpoint and its relation to the main control UART remain open.

## STM32 command tokenizer

The STM32 dispatcher first calls `FUN_080041f0`, which clears a 100-byte scratch area and copies the incoming ASCII command into ten-byte slots, one space-delimited token per slot (up to nine tokens). This explains the fixed offsets used by the command handlers. For `M678`, slot 0 is the opcode; subsequent value slots begin at offsets `0x0b`, `0x15`, `0x1f`, `0x29`, `0x33`, `0x3d`, and `0x47`. The numeric helper used by the dispatcher parses decimal values. This is a firmware implementation detail; it does not change the Linux-side 100-byte padded frame described above.

## STM32 application commands found in PrinterUI and `V1-01.bin`

The following strings and call sites are present in both sides of the control link. The control firmware dispatcher, USART1 receive gate, and several parameter paths have now been statically recovered. The live byte transcript is still limited to startup; the electrical layer, some parameter units, and edge cases still need passive capture or further analysis.

### Traced UI-start exchange

To test tracing without attaching to the existing process, the idle PrinterUI was briefly restarted as a child of `strace -f` by manually invoking its existing `S99cxpm-ui` service entry. No persistent init file was edited, and the distinct `S21stm32_update` service was not run. The device accepted this launch-time trace. It opened `/dev/ttyS2` with `O_RDWR|O_NOCTTY|O_NONBLOCK` (fd 27 in that run), sent two 101-byte requests, then read the replies one byte per syscall:

```text
TX: "V114" + spaces through byte 95 + 55 55 55 55 0a
RX: "89\n"
TX: "MODELS:A" + spaces through byte 95 + 55 55 55 55 0a
RX: "GET MODELS:A OK\n"
```

The `V114`/`89` pair is consistent with a version query and the firmware string `SWV1.89`, although the wire response itself contains only `89`. This captured startup sequence confirms the common frame padding/trailer, the version response, and the `MODELS:A` reply format. It does not cover periodic idle queries or a print layer. The broad trace slowed startup enough that PrinterUI reported a heap-corruption error; the trace was stopped, its temporary files were removed from the device, and the normal UI service was restarted and verified with `TracerPid=0`. No print, UV, or motor action was initiated. See [emulator and tracing experiments](emulation.md) for the QEMU and Renode results and limits.

| Family | Observed command/string | Current interpretation |
|---|---|---|
| Version/model handshake | `V114`, `MODELS:`, `MODELS `, `GET MODELS:%s OK` | Startup trace captures `V114` → `89\n` and `MODELS:A` → `GET MODELS:A OK\n`; the version interpretation is consistent with `SWV1.89` in the MCU image. |
| Z axis | `G0 Z500 F… D1 S1/S0 H…`; `G0 Z… F… D0 S1/S0 H…` | UI builders label the first command “up” and the second “down”; `F` is a speed-like parameter, `H` is the configured helical pitch, and `S` selects the external/non-external motor variant. |
| Position/status | `M114`, `M113`, `M108`, `M410 S0/S1/S2` | `M108` returns three sampled GPIO levels as `M108_<0|1>_<0|1>_<0|1>`; the raw register bases and masks are below. `M410` always emits `M410_OK1`; its state-reset/stop behavior depends on current controller state, and exact meanings for S0/S1/S2 are not fully recovered. |
| Layer operation | `M678 Z… U… D… T… P… M… L…` | PrinterUI builds this exact ordered template for first, bottom, and regular layers. STM32 emits `M678_Busy` before parsing the seven values, then sets busy state and wakes a worker task. This is an acceptance/busy reply, not a completion reply. The CL60 LCD loop waits for the matching reply and motor status; `WaitMotorStatus` polls `M114` but accepts only the exact returned string `M114 `, which excludes the known STM32 replies. The runtime effect of this apparent response mismatch remains unverified. |
| Temperature | `M105`, `M105 T… ON`, `M105 T OFF`; reply template `M105_TA…_TB…` | Temperature query/report and on/off control paths. |
| UV/light | `M42 P36 M1 S0` / `M42 P36 M1 S1`; `M355 P1 C…` | UI names the `M42` calls `openLight`/`closeLight`; the MCU replies `M42_OK_LED` and updates output state. Its model-dependent branches write either a timer-like register or GPIO set/reset registers; the board-level signal mapping is unknown. `M355_OK` is emitted before argument/model validation. Only modes C/D with token 1 exactly `P1` and token 2 containing `C` send the 10-byte parameter packet and a fixed 3-byte record over USART3; each transfer is separated from the next by an event-bit wait. |
| Fans/outputs | `M106`, `M107`, `M108`, `M106 P1 S0/S255`, `M106 P2 …` | `M106` changes mode-dependent output state; model C plus `P1 S255` additionally emits `M106_RUNEND` and sends two fixed 3-byte records twice each. `M107` and, in modes B/G, `M108` forward the entire original mailbox to USART2/3 with no immediate ACK. `M108` in other modes samples three GPIO bits and replies with their levels. Physical pin functions remain unknown. |
| Other | `M800`, `M800 S0`, `M800_OK` | The firmware replies `M800_OK` immediately. Exact token `S0` then runs a seven-stage USART3 DMA exchange with event waits and per-stage delays; there is no separate completion ACK. Packet contents and meanings remain unresolved. |

`M108` in modes other than B/G takes no argument in the local handler. It samples three digital input bits and returns them as decimal 0/1 fields separated by underscores: mask `0x04` at peripheral base `0x40010800`, then masks `0x02` and `0x04` at `0x40010c00`. In B/G it forwards the original mailbox instead. The MCU memory map is consistent with STM32F1 GPIO blocks, but the exact part and board-level pin functions have not been confirmed. The response shape is statically established; these bit values have not been captured live.

`M107` is an auxiliary UART forwarder in this firmware, not a locally handled fan-off command. The dispatcher compares the model mode byte at `0x20000000`: mode B sends the original mailbox through USART2 TX (`FUN_08003580`, DMA1 channel 7); mode G sends it through USART3 TX (`FUN_08003630`, DMA1 channel 2). Other modes return without an ACK. It does not validate parameter tokens; the byte count is `strlen(mailbox)`, and the DMA helper splits sends into chunks of at most 100 bytes. Because the mailbox is not explicitly NUL-terminated at the received length, the exact forwarded byte count and inclusion of trailer/LF or stale tail bytes are not established without a passive capture.

In the same model B/G branches, `M108` also forwards the complete original mailbox to USART2/3 without a local ACK. Its other model branches implement the GPIO query above. USART2/3 RX IDLE handlers relay received text back on USART1 as `%s\n`, so auxiliary replies arrive at the host as lines on the main control link. The secondary UART's physical destination and response syntax are not identified.

`M106` has two parameter routes and no general ACK. For `P1` with token 2 exactly `S0` or `S255`, model B writes 0/1 to aliases at `0x422201bc` and `0x422201b8`, plus the alias byte at `0x422201ba`; model G writes only the alias byte at `0x422201ba`; other modes write the alias byte and `0x422201b8`. These are raw memory/bit-band writes, not identified board pins. In model C, `M106 P1 S255` additionally emits `M106_RUNEND\n`, waits 20 ms, then sends two 3-byte records twice each from `0x2000012f` and `0x20000132`, with 20 ms spacing. Their bytes are not modified by this handler and remain unresolved. For `P2`, mode B reads token-2 characters 1–3 (`'1'` maps to 0, any other character to 1) into three output states; other modes use two characters for two states. A token exactly `S00` in that non-B branch enters a busy loop until the mode byte becomes C, then sends one 3-byte record from `0x20000138`; if the mode never becomes C, the loop has no timeout in the reviewed path.


`M355` is an auxiliary serial protocol, not SPI in the recovered path. The handler emits `M355_OK\n` immediately, before validating parameters or the model, so this reply is not proof that a transfer happened. Only model modes C/D, token 1 exactly `P1`, and token 2 containing the character `C` enter the transfer branch. The decimal value after the first `C` is reduced to its low 16 bits. The 10-byte packet at `0x20000125` has three unchanged header bytes, the low/high value bytes repeated at offsets 3–8, then byte 9 equal to the low byte of the one's-complement sum of bytes 0–8. It is sent through USART3 TX, then the handler waits on event bit 0 at object `0x20000030` (clear-on-exit, timeout argument 500), sends the fixed three-byte record at `0x20000122`, and waits on the same bit again. Modes C/D configure USART3 at 9,600 baud. USART3 RX can signal that event and relays its received text as `%s\n` over USART1. The three header bytes, fixed record bytes, accessory identity, and RTOS tick duration remain unknown.

`M410` always emits `M410_OK1\n` before its state-dependent body. If `0x20000091 == 1`, it parses token 1 after its first character; only value 2 (the usual `S2` spelling) performs the reset path. S0, S1, and a missing argument are no-ops in this branch. S2 clears bit 0 at timer/register `0x40000400`, zeros `0x20000068`, `0x20000077`, `0x20000078`, `0x20000074`, and `0x20000091`, sets output alias `0x422201bc`, calls a model-specific reset helper (C/D can send a 3-byte USART3 record; other modes use a bit-banged path, with E/F-specific output handling), clears byte `0x20000076`, and signals mask `0x1` on object `0x20000024`. If `0x20000091 != 1`, it ignores the S parameter: byte `0x20000095 == 0` clears bit 0 at `0x40000000` and zeros `0x20000384`; otherwise mode E starts a `0x640` countdown at `0x200003a0` and sets bit 0 at `0x40000800` unless state byte `0x20000078` is 1 or 3, then busy-waits for the counter to reach zero. Other modes clear that timer bit and counter. These are build-specific state/register effects; the physical outputs and timer units are unknown. No `M410` command was sent.

`M800` always emits `M800_OK\n`; exact token 1 `S0` additionally calls the seven-stage USART3 exchange routine. Its stage table is:

| Stage | Source RAM | Length | Post-send delay |
|---:|---:|---:|---:|
| 0 | `0x20000116` | 3 | 6500 ms |
| 1 | `0x20000135` | 3 | 150 ms |
| 2 | `0x20000119` | 3 | 150 ms |
| 3 | `0x20000125` | 10 | 150 ms |
| 4 | `0x20000122` | 3 | 150 ms |
| 5 | `0x2000012f` | 3 | 150 ms |
| 6 | `0x20000132` | 3 | none |

The routine waits on event mask `1` (bit 0) at `0x20000030` with timeout argument 500 around each stage. USART3 RX copies received DMA bytes from `0x20000a28` into scratch at `0x20000960`, relays them as `%s\n` over USART1, then signals that event; it does not parse accessory fields. On a successful wait, scratch byte `0x20000962` (offset 2) is inspected: if it is not `0xff`, the routine advances to the next stage; otherwise, or if the wait fails, it clears the first four scratch bytes and resends the current packet. No minimum receive length is checked before reading offset 2. Stage 0 has at most five sends; the outer pass limit is 60, and successful stage 6 terminates the routine. Modes C/D also call this routine during startup after setting USART3 to 9,600 baud. The packet bytes and device-side meanings are unresolved; `M800_OK` is the command response, not a completion report for the exchange.

The seven packet addresses are in a startup-initialized RAM region (`0x20000000`–`0x200001ef`). In the analyzed command/exchange paths, the only write found to these payloads is `M355` updating bytes 3–9 of the 10-byte block at `0x20000125`; its first three bytes and the other six `M800` blocks are only read and sent. The extracted MCU image's initialization metadata points at this RAM region, but the referenced initialization callback is at the exact end of the 33,236-byte image, so the initial packet contents cannot be recovered from this artifact. Do not infer that these bytes are zero or uninitialized.

The MCU image contains response/status strings such as `M114_OK`, `M114_OK1`, `M114_Busy`, `M113_OK`, `M113_OK1`, `M113_Busy`, `M410_OK1`, `M678_Busy`, `M105_OK_ON`, and `M105_OK_OFF`. `M113` and `M114` share a raw busy-state predicate: the dispatcher adds byte fields at `0x20000075`, `0x20000076`, and `0x20000091`, plus words at `0x20000384` and `0x200003a0`. A nonzero aggregate selects a `Busy` reply. If bytes `0x20000075` and `0x20000076` are both `1`, it formats `Busy_%d` with byte `0x20000077`; otherwise it emits the plain `Busy` string. In the zero-busy `OK`/`OK1` branches, the dispatcher reads mask `0x20` through a GPIO helper for peripheral base `0x40010800`; the pin's board-level function is unknown. `M114` also consumes a one-shot bit from the event object referenced by `0x2000001c` and returns `M114_DELATLIGHT_OVER` when that bit was set. This event is the same bit set by the `M678` worker's state-7 path described below. These are raw addresses from this firmware build, not stable API names or units. `G0` replies `G0_Busy` and parses its `Z/F/D/S/H` words; the firmware then dispatches a motor action. Exact state meaning and completion timing still need live evidence.

### `M678` fields recovered from both ends

PrinterUI's literal template is `M678 Z%1 U%2 D%3 T%4 P%5 M%6 L%7 ` (including a trailing space). For the active profile, the first-layer builder, initial-exposure builder, and regular-layer builder all populate this command, while the actual bitmap is submitted through the separate display path. The STM32 tokenizer parses the words from these slots:

| Word | Token value offset in STM32 scratch | What is established |
|---|---:|---|
| `Z` | `0x0b` | Decimal value parsed and stored; UI takes it from a profile field. |
| `U` | `0x15` | Decimal value parsed and stored; UI currently formats the same profile field used for `D`. |
| `D` | `0x1f` | Decimal value parsed and stored; UI currently formats the same profile field used for `U`. |
| `T` | `0x29` | Decimal exposure-related value; first-layer and normal-layer builders source it from different job/profile values. |
| `P` | `0x33` | Value scaled by 1000 by the UI's first-layer builder; normal-layer builder uses a floating profile value. |
| `M` | `0x3d` | Value scaled by 1000 by the UI; exact firmware meaning is not named. |
| `L` | `0x47` | Value is calculated from the parsed layer/job data by PrinterUI; exact firmware meaning and units are not named. |

The STM32 stores these parsed values as binary64 pairs at build-specific RAM addresses. `U`, `D`, `P`, `M`, and `L` are copied directly. `Z` and `T` are each multiplied by the binary64 constant `2.04345703125` before storage. The observed destinations are:

| Word | STM32 RAM destination | Transformation before storage |
|---|---:|---|
| `U` | `0x200000b0` | Parsed binary64 copied directly |
| `D` | `0x200000b8` | Parsed binary64 copied directly |
| `Z` | `0x200000c0` | Parsed binary64 × `2.04345703125` |
| `T` | `0x200000c8` | Parsed binary64 × `2.04345703125` |
| `P` | `0x200000d0` | Parsed binary64 copied directly |
| `M` | `0x200000d8` | Parsed binary64 copied directly |
| `L` | `0x200000e0` | Parsed binary64 copied directly |

The current static call paths use `Z` and `U` in the initial worker action, use `T`, `Z`, and `U` in a later timed phase, feed `L` through an integer conversion into a ten-entry history array, and combine `M` and `P` in later timer/counter arithmetic. `D` is parsed and stored, but the reviewed direct global-reference scan found no read of `0x200000b8`; it may be reserved, consumed indirectly, or unused in this build. These are data-flow findings only; they do not name units or assign physical meaning to the fields.

The dispatcher also reads token slot 8 at scratch offset `0x50`, beyond the seven named words. An exact `P2` token takes a bit-band-output branch. The same slot is then compared with exact `S`: exact `S` skips the numeric-array path; otherwise the dispatcher parses the substring after the first character and fills a ten-word array with the converted value. With the ordinary PrinterUI template, slot 8 is empty, so the numeric helper receives an empty string and the array is initialized with zero. The electrical function of the bit-band writes and the intended public syntax remain unknown.

### `M678` asynchronous state and completion path

The state byte at `0x20000077` is both a status suffix source (`M113_Busy_%d` / `M114_Busy_%d`) and a worker-state selector. Static disassembly gives this flow:

1. On a matching `M678`, the dispatcher first transmits `M678_Busy\n`. It then parses/stores the parameters, sets bytes `0x20000076 = 1`, `0x20000075 = 1`, and `0x20000077 = 0`, and sets event-group bit 0 on the object referenced by `0x20000024` if that bit is not already set.
2. A worker waits on bit 0 of that event object (with a 1000-tick wait argument in this build). It advances the layer routine only when both busy bytes `0x20000076` and `0x20000075` equal 1. That routine selects on the state byte and advances through the numeric states 1, 2, 3, 4, 5, and 6; it also has a state-7 path that advances to 8 and signals bit 0 on a second event object referenced by `0x2000001c`. The `M114` handler consumes that same bit and emits the one-shot `M114_DELATLIGHT_OVER` reply. State 6 itself has no transition in the reviewed routine, so another asynchronous/timer path must advance it.
3. The timer-side routine at `0x080028c8` compares raw counters at `0x20000068`, `0x2000006c`, and `0x20000070`, with additional state at `0x20000074` and `0x20000078`. It can set the worker state to 7. Its terminal branch writes `0x20000077 = 100`, clears busy bytes `0x20000076` and `0x20000075`, and clears `0x20000074`/`0x20000078`.
4. `M113` and `M114` report a busy response while their shared raw busy aggregate is nonzero. If both busy bytes are 1, the reply includes the current state byte; otherwise the reply is plain `Busy`. When the timer path clears the busy bytes, the status handler can return `OK`/`OK1` even though the state byte has just been set to 100. Thus 100 is established as an internal terminal marker, not a guaranteed wire-visible completion response.

The STM32 state-7 worker sets the event bit that the `M114` handler can consume as `M114_DELATLIGHT_OVER`. A DLP-specific PrinterUI workflow sends `M114` before `openLight`, which is consistent with a phase gate in that workflow. The active CL60 LCD path also sends M114 indirectly through `WaitMotorStatus`; static host analysis shows that this helper accepts only the exact returned string `M114 `. The CXSerial parser turns the firmware sentinel into `_DELATLIGHT_OVER\n`, which does not satisfy the helper's `M114 ` filter/compare. The raw M114 response that does satisfy this path, if any, and the runtime consequence of the mismatch remain unverified without a layer UART trace. The LCD loop does not call `openLight` from its per-layer code, so the DLP sequence cannot be projected onto CL60. The worker's numbered states describe internal phases, not layer numbers or percentages. Exact timing units, event-object ownership, motor/light operations performed in each phase, and the point where the display path gates the MCU remain unresolved. No `M678` command was sent; these conclusions come from the shipped binary and PrinterUI templates.

## STM32 ROM bootloader protocol

The Linux rootfs includes `stm32flash 0.5`. The `stm32_update` startup script controls the H616-side BOOT0 and RESET lines, then invokes `stm32flash` on the same UART to identify and write STM32 flash at `0x08000000`. This is separate from the printer's ASCII/G-code-like application protocol. ST documents the USART system bootloader in [AN3155](https://www.st.com/resource/en/application_note/an3155-usart-protocol-used-in-the-stm32-bootloader-stmicroelectronics.pdf) and boot-mode selection in [AN2606](https://www.st.com/resource/en/application_note/an2606-introduction-to-system-memory-boot-mode-on-stm32-mcus-stmicroelectronics.pdf).

The updater's `stm32flash` information command omits `-b`, so the utility's own default is 57,600 baud; the normal application UART is restored to 115,200 after the update path. The exact STM32 part and its ROM bootloader revision are not known, so its supported USART pins, ROM commands, and read-protection state are not established. `stm32flash` supports read (`-r`) as a utility capability, but Creality's startup script does not invoke it and we did not attempt a read.

## Still needed for a complete protocol spec

- A passive UART capture during idle, status query, manual Z movement, light control, and a harmless temperature query.
- Board photographs or electrical probing to identify the UART connector, logic levels, MCU marking, reset/BOOT0 routing, and the display connectors.
- A longer but less perturbative passive UART capture for periodic idle queries and print-layer synchronization. Launch-time `strace -f` works where attaching to the existing PID is denied, but tracing all startup file I/O perturbs this UI build. A second reader on `/dev/ttyS2` is not safe because it could consume PrinterUI replies.
- The remaining `M678` physical semantics and units, exact timer tick rate, how the display path gates MCU phases, `M410`/`M355` state semantics, and the complete direct `MengTool` command path.
- The full STM32 interrupt/peripheral/register map and resolved names for the many remaining functions. Ghidra pseudocode, the 257-function index, and string cross-references are available privately; this public project does not redistribute the vendor image or pseudocode.
