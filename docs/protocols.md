# Protocol map

This page separates the Linux-to-controller serial protocol, the STM32 application commands, and the STM32 ROM programming protocol. Findings below come from the running Linux process, the PrinterUI decompilation, and the firmware shipped in the downloaded update. We did not capture live UART bytes, reset the MCU into ROM mode, or send test commands.

## Linux UART to printer controller

| Property | Finding | Evidence |
|---|---|---|
| Linux device | `/dev/ttyS2` | Open by the live `PrinterUI` process; selected by the startup STM32 updater for this product |
| SoC controller | Allwinner UART2 at `0x05000800` | Flattened device tree and sysfs |
| Application baud | 115,200 baud | `MainView::InitSerialPort` argument and live `stty` state |
| Frame parameters | 8 data bits, no parity, 1 stop bit, no hardware/software flow control | Live `stty` state and `CXSerial` constructor |
| Physical endpoint | Control MCU path is confirmed by the update script and bundled STM32 image; PCB connector, MCU UART pins, voltage, and wire direction remain untraced | Static firmware/script evidence; no board photo or live capture |

The `CD60` and `D160` product branches select `/dev/ttyS3`; the other branch selects `/dev/ttyS2`. The inspected unit reports `CL60`.

## Control UART versus layer-image path

The UART is the STM32 control/status channel: it carries the ASCII-like commands and line replies described below. CL60 layer bitmaps use a separate H616 video-output path. The active `CL60` profile in `halotMachine.xml` selects `CreateVideoOutport`, source dimensions 1620×2560, compressed dimensions 540×2560, and `RgbRange=BGRA`. Static analysis of `writerClearImage` shows each output pixel is built from three consecutive source samples and an opaque alpha byte. The running kernel shows the 540×2560 mode entering the RK628 HDMI receiver before MIPI DSI1. Thus the large exposure bitmap is not framed into the 100-byte UART command protocol. The software-side pixel packing is recovered; the exact downstream RK628/DSI mapping to panel columns remains open. See [the display data path](display-pipeline.md).

## PrinterUI serial framing

The normal `CXSerial::SendMsgToSerial` path constructs a fixed 100-byte ASCII body and appends line feed (`0x0a`):

| Offset | Bytes | Meaning inferred from code |
|---:|---|---|
| 0–95 | Command bytes, then ASCII spaces (`0x20`) | The caller's final character is dropped before copying; observed command templates commonly end in a trailing space |
| 96–99 | `55 55 55 55` | Fixed trailer |
| 100 | `0a` | Line-feed terminator |

The code computes a 16-bit additive sum over bytes 0–95, but the value is not copied into the outgoing frame. A separate `parserSerialMsg` routine compares such a sum with bytes 0–1 of an input buffer; no call to that routine was found in the active receive call paths examined. Treat the checksum routine as legacy or otherwise unresolved, not as proof that the normal transmitted frame carries a checksum.

Replies are read with `readline` using LF, with a 100-byte maximum. `getRecvTypeAndMsg` splits reply text on `_`; for example, the firmware contains the format string `M105_TA%0.1f_TB%0.1f`, which implies a reply shaped like `M105_TA…_TB…`. PrinterUI maps the first field to the command type and stores the rest as the response associated with that command.

There is also a `SendMsgMengToSerial` / `RecvMsgMengFromSerial` path. It writes its string directly rather than applying the 100-byte wrapper and reads an LF-terminated line. The decompiled `ThreadWorkMengTool` calibration/light workflow uses this path. Exact command strings in every MengTool branch have not yet been fully mapped.

## STM32 command tokenizer

The STM32 dispatcher first calls `FUN_080041f0`, which clears a 100-byte scratch area and copies the incoming ASCII command into ten-byte slots, one space-delimited token per slot (up to nine tokens). This explains the fixed offsets used by the command handlers. For `M678`, slot 0 is the opcode; subsequent value slots begin at offsets `0x0b`, `0x15`, `0x1f`, `0x29`, `0x33`, `0x3d`, and `0x47`. The numeric helper used by the dispatcher parses decimal values. This is a firmware implementation detail; it does not change the Linux-side 100-byte padded frame described above.

## STM32 application commands found in PrinterUI and `V1-01.bin`

The following strings and call sites are present in both sides of the control link. The control firmware dispatcher and several parameter paths have now been statically recovered. The live byte transcript, electrical layer, some parameter units, and edge cases still need passive capture or further analysis.

### Traced UI-start exchange

To test tracing without attaching to the existing process, the idle PrinterUI was briefly restarted as a child of `strace -f` by manually invoking its existing `S99cxpm-ui` service entry. No persistent init file was edited, and the distinct `S21stm32_update` service was not run. The device accepted this launch-time trace. It opened `/dev/ttyS2` with `O_RDWR|O_NOCTTY|O_NONBLOCK` (fd 27 in that run), sent the following 101-byte request, then read the reply one byte per syscall:

```text
TX: "MODELS:A" + spaces through byte 95 + 55 55 55 55 0a
RX: "GET MODELS:A OK\n"
```

Before that request, the trace recorded three unexplained inbound bytes, `38 39 0a` (`"89\n"`; each byte arrived in a separate read), with no host write on the UART immediately before them. Their meaning is unresolved. This single startup sample confirms the frame padding/trailer and the `MODELS:A` reply format. It does not cover the periodic idle queries or a print layer. The broad trace slowed startup enough that PrinterUI reported a heap-corruption error; the trace was stopped, its temporary files were removed from the device, and the normal UI service was restarted and verified with `TracerPid=0`. No print, UV, or motor action was initiated. See [emulator and tracing experiments](emulation.md) for the QEMU results and limits.

| Family | Observed command/string | Current interpretation |
|---|---|---|
| Version/model handshake | `V114 `, `MODELS:`, `MODELS `, `GET MODELS:%s OK` | PrinterUI sends `V114 ` and later a `MODELS:` request; the image contains `SWV1.89`. The exact complete request/reply transcript is inferred from strings and call order, not captured. |
| Z axis | `G0 Z500 F… D1 S1/S0 H…`; `G0 Z… F… D0 S1/S0 H…` | UI builders label the first command “up” and the second “down”; `F` is a speed-like parameter, `H` is the configured helical pitch, and `S` selects the external/non-external motor variant. |
| Position/status | `M114`, `M113`, `M108`, `M410 S0/S1/S2` | Used by status, homing, stop, or busy-state paths; exact `M410` submode meanings are not fully recovered. |
| Layer operation | `M678 Z… U… D… T… P… M… L…` | PrinterUI builds this exact ordered template for first, bottom, and regular layers. STM32 immediately replies `M678_Busy`, then parses all seven decimal parameters and updates print/motor state. `M113`/`M114` are separate state queries used by the UI while it waits. The field names/order are certain; units and every field's role in the controller state are not. |
| Temperature | `M105`, `M105 T… ON`, `M105 T OFF`; reply template `M105_TA…_TB…` | Temperature query/report and on/off control paths. |
| UV/light | `M42 P36 M1 S0` / `M42 P36 M1 S1`; `M355 P1 C…`; `M355` | UI functions name the `M42` calls `openLight`/`closeLight`; the MCU replies `M42_OK_LED`. The `M355 P1 C…` handler replies `M355_OK`, builds a 10-byte SPI payload containing the 16-bit `C` value repeated three times, and appends the low byte of the one's-complement sum of bytes 0–8. It then sends fixed 3-byte SPI commands with 500 ms waits. The fixed packet header and the electrical target of this SPI path remain unresolved. |
| Fans/outputs | `M106`, `M107`, `M106 P1 S255`, `M107 P1 S0/S255` | Fan/output control strings; output labels and electrical mapping remain unconfirmed. |
| Other | `M800`, `M800_OK`, `M42_OK_LED` | Present in firmware strings; purpose not yet determined. |

The MCU image contains response/status strings such as `M114_OK`, `M114_OK1`, `M114_Busy`, `M113_OK`, `M113_OK1`, `M113_Busy`, `M410_OK1`, `M678_Busy`, `M105_OK_ON`, and `M105_OK_OFF`. `M113` and `M114` select among ready/busy replies from internal state flags; `M114` also has a `M114_DELATLIGHT_OVER` response when its light timer expires. The `OK1` distinction is preserved here without assigning it an undocumented meaning. `G0` replies `G0_Busy` and parses its `Z/F/D/S/H` words; the firmware then dispatches a motor action. Exact state-flag meanings, all numeric units, and completion timing still need live evidence.

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

These statements describe data flow, not guessed units. The firmware parses the command and starts its internal state changes after emitting `M678_Busy`; the UI polls other commands for motion/exposure state. No `M678` test was sent.

## STM32 ROM bootloader protocol

The Linux rootfs includes `stm32flash 0.5`. The `stm32_update` startup script controls the H616-side BOOT0 and RESET lines, then invokes `stm32flash` on the same UART to identify and write STM32 flash at `0x08000000`. This is separate from the printer's ASCII/G-code-like application protocol. ST documents the USART system bootloader in [AN3155](https://www.st.com/resource/en/application_note/an3155-usart-protocol-used-in-the-stm32-bootloader-stmicroelectronics.pdf) and boot-mode selection in [AN2606](https://www.st.com/resource/en/application_note/an2606-introduction-to-system-memory-boot-mode-on-stm32-mcus-stmicroelectronics.pdf).

The updater's `stm32flash` information command omits `-b`, so the utility's own default is 57,600 baud; the normal application UART is restored to 115,200 after the update path. The exact STM32 part and its ROM bootloader revision are not known, so its supported USART pins, ROM commands, and read-protection state are not established. `stm32flash` supports read (`-r`) as a utility capability, but Creality's startup script does not invoke it and we did not attempt a read.

## Still needed for a complete protocol spec

- A passive UART capture during idle, status query, manual Z movement, light control, and a harmless temperature query.
- Board photographs or electrical probing to identify the UART connector, logic levels, MCU marking, reset/BOOT0 routing, and the display connectors.
- A longer but less perturbative passive UART capture for periodic idle queries and print-layer synchronization. Launch-time `strace -f` works where attaching to the existing PID is denied, but tracing all startup file I/O perturbs this UI build. A second reader on `/dev/ttyS2` is not safe because it could consume PrinterUI replies.
- The remaining `M678`/`M410`/`M355` state semantics and units, and the complete direct `MengTool` command path.
- The full STM32 interrupt/peripheral/register map and resolved names for the many remaining functions. Ghidra pseudocode, the 257-function index, and string cross-references are available privately; this public project does not redistribute the vendor image or pseudocode.
