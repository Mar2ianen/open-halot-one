# Protocol map

This page separates the Linux-to-controller serial protocol, the STM32 application commands, and the STM32 ROM programming protocol. Findings below come from the running Linux process, the PrinterUI decompilation, and the firmware shipped in the downloaded update. We have one syscall-level PrinterUI startup trace, but no independent electrical UART capture; we did not reset the MCU into ROM mode or send test commands.

## Linux UART to printer controller

| Property | Finding | Evidence |
|---|---|---|
| Linux device | `/dev/ttyS2` | Open by the live `PrinterUI` process; selected by the startup STM32 updater for this product |
| SoC controller | Allwinner UART2 at `0x05000800` | Flattened device tree and sysfs |
| Application baud | 115,200 baud | `MainView::InitSerialPort` argument and live `stty` state |
| Frame parameters | 8 data bits, no parity, 1 stop bit, no hardware/software flow control | Live `stty` state and `CXSerial` constructor |
| STM32 application UART | The firmware's command mailbox is populated by the STM32 USART1 RX path | Static disassembly links USART1 DMA RX to the buffer consumed by the command dispatcher |
| Physical endpoint | The update script and PrinterUI both use Linux `/dev/ttyS2`; this strongly suggests it reaches the MCU application UART, but the board trace, connector, STM32 pins, voltage, and wire direction remain unverified | Linux runtime/script evidence plus MCU firmware disassembly; no board photo or electrical capture |

The `CD60` and `D160` product branches select `/dev/ttyS3`; the other branch selects `/dev/ttyS2`. The inspected unit reports `CL60`.

### STM32 UART and DMA setup recovered in Renode

The raw application image was run in Renode against its STM32F103 platform with a deliberately minimal RCC stub. CPU writes to the STM32F1 register map configure:

| MCU peripheral | Firmware configuration observed | Interpretation |
|---|---|---|
| USART1 RX | DMA1 channel 5; `CPAR=0x40013804`, `CMAR=0x20000578`, `CNDTR=0xc8`, then channel enable | 200-byte peripheral-to-memory receive buffer |
| USART2 RX | USART2 CR3 `DMAR` set; DMA1 channel 6; `CPAR=0x40004404`, `CMAR=0x200007d0`, `CNDTR=0xc8`, then channel enable | 200-byte peripheral-to-memory receive buffer |
| USART2 TX | USART2 CR3 `DMAT` set; DMA1 channel 7 points at `0x40004404` and RAM buffer `0x20000640`; initial transfer count is zero | Memory-to-peripheral transmit path, likely armed when a reply is sent |

The DMA channel mappings and register addresses are consistent with an STM32F1-style peripheral map. Linux `/dev/ttyS2` identifies Allwinner UART2. Static disassembly ties the STM32 command parser to **USART1 RX**; USART2 has a separate RX/TX DMA setup. The likely host-to-MCU path is H616 UART2 (`/dev/ttyS2`) to STM32 USART1, although the exact PCB routing remains unverified. Renode recovered peripheral configuration only: DMA was a memory-backed stub, so it produced no UART bytes or protocol transcript and provides no transfer-timing evidence. Renode's [STM32F103 platform](https://github.com/renode/renode/blob/master/platforms/cpus/stm32f103.repl) is a base rather than a full model of the exact Creality MCU; missing blocks can be added using its [Python peripheral mechanism](https://renode.readthedocs.io/en/latest/basic/using-python.html).

### STM32 receive framing and interrupt path from static disassembly

This path was recovered directly from `V1-01.bin`, not from Renode's nonfunctional DMA stub:

1. STM32 USART1 uses DMA1 channel 5 with a 200-byte RX area at `0x20000578`. On USART1 IDLE, the handler at `0x08003078` tests USART `CR1.IDLEIE` and `SR.IDLE` (helper at `0x080033f8`, encoded selector `0x424`), then reads the data register via `0x08003570`. It disables DMA, samples `CNDTR`, reloads the 200-byte transfer and buffer address, copies `200 - CNDTR` received bytes to `0x200004b0`, and reenables DMA.
2. A separate consumer task at `0x08006ddc` reads the mailbox at `0x200004b0`. It dispatches the command only when byte offset `0x63` (decimal 99) equals `0x55` (`'U'`), then calls the command dispatcher at `0x08005510`.
3. The dispatcher tokenizes the first 100 bytes with `0x080041f0`: up to nine space-separated ten-byte slots. Thus the four `0x55` bytes at offsets 96–99 in PrinterUI's fixed body act as a frame marker; the active STM32 gate checks the last one. The LF sent by PrinterUI is byte 100, after the checked 100-byte body.

This closes the software-side receive framing: command payload, fixed `0x55` trailer, marker position, IDLE-triggered DMA handoff, and dispatcher entry point are all visible in the shipped MCU image. It does not establish electrical pin mapping or prove how fragmented frames across multiple IDLE gaps are handled. The separate `parserSerialMsg` checksum routine still has no active call path identified.

USART1 also has a static special-case check for the ASCII string `reboot` in the received mailbox; a match requests a Cortex-M system reset. No such command was sent. The normal PrinterUI startup trace contains only `V114` and `MODELS:A`.

The other IRQs are distinct: USART2 uses DMA1 channel 6 for RX and channel 7 for TX; USART3 uses DMA1 channel 3 for RX. USART2's startup DMA mapping alone does not identify the PrinterUI control link. The vector table points USART1/2/3 IRQs to handlers at `0x08003078`, `0x080031a0`, and `0x0800321c`; DMA1 channel7 has a custom handler at `0x08001252`, while channel5/6 vectors point to the default handler. USART3 is not otherwise tied to PrinterUI by current evidence.

## Control UART versus layer-image path

The UART is the STM32 control/status channel: it carries the ASCII-like commands and line replies described below. CL60 layer bitmaps use a separate H616 video-output path. The active `CL60` profile in `halotMachine.xml` selects `CreateVideoOutport`, source dimensions 1620×2560, compressed dimensions 540×2560, and `RgbRange=BGRA`. Static analysis of `writerClearImage` shows each output pixel is built from three consecutive source samples and an opaque alpha byte. The running kernel shows the 540×2560 mode entering the RK628 HDMI receiver before MIPI DSI1. Thus the large exposure bitmap is not framed into the 100-byte UART command protocol. The software-side pixel packing is recovered; the exact downstream RK628/DSI mapping to panel columns remains open. See [the display data path](display-pipeline.md).

### PrinterUI layer and exposure synchronization

The static `SerialPortPrintFile::lcdPrint` path prepares `M678`, waits for the asynchronous file parser to produce the layer, submits the image through `SendBgraImage`, and then sends `M678` over the control UART. It waits for the matching UART reply and calls `WaitMotorStatus`; only after that succeeds does it wait the configured exposure delay and call `doExposure`. The separate `dlpPrintCxline` path sends `M678` before submitting the image, then waits for the reply and motor status. These are function-specific orderings recovered from the PrinterUI binary; neither carries the bitmap inside the serial frame.

`doExposure` sends an `M114` query until the serial helper reports the matching response, then calls the UI's `openLight` path (`M42 P36 M1 S0`). The exposure result comes from `YuvDataSend::waitExposureFinished` through the display-output backend. The wrapper polls about every 220 ms while the result is 4; result 2 causes one retry after a 1-second delay; code 5 is the success case accepted by `doExposure`. Therefore `M678_Busy` and `M113`/`M114` describe the STM32 control/motion state, while the UI's exposure-complete decision is sourced from the independent display-output path. The callback/event source and the precise condition coupling an MCU phase to a displayed frame are not recovered yet. See [PrinterUI's call-path notes](printerui-analysis.md) and [the display data path](display-pipeline.md).

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
| Layer operation | `M678 Z… U… D… T… P… M… L…` | PrinterUI builds this exact ordered template for first, bottom, and regular layers. STM32 emits `M678_Busy` before parsing the seven values, then sets busy state and wakes a worker task. This is an acceptance/busy reply, not a completion reply. `M113`/`M114` are separate status queries used while the asynchronous state machine runs. |
| Temperature | `M105`, `M105 T… ON`, `M105 T OFF`; reply template `M105_TA…_TB…` | Temperature query/report and on/off control paths. |
| UV/light | `M42 P36 M1 S0` / `M42 P36 M1 S1`; `M355 P1 C…` | UI names the `M42` calls `openLight`/`closeLight`; the MCU replies `M42_OK_LED` and updates output state. Its model-dependent branches write either a timer-like register or GPIO set/reset registers; the board-level signal mapping is unknown. `M355 P1 C…` replies `M355_OK`, builds a 10-byte SPI payload containing the 16-bit `C` value repeated three times, and appends the low byte of the one's-complement sum of bytes 0–8. It then sends fixed 3-byte SPI commands with 500 ms waits. Packet header and electrical target remain unresolved. |
| Fans/outputs | `M106`, `M107`, `M106 P1 S255`, `M107 P1 S0/S1/S255` | These strings occur in PrinterUI. The STM32 changes output-related state in both command branches; one `M106` route emits `M106_RUNEND`. Exact channel names, value semantics, and physical output mapping remain unknown. |
| Other | `M800`, `M800 S0`, `M800_OK` | The firmware replies `M800_OK`; `M800 S0` additionally enters an indirect, state-selected routine whose effect is not identified. |

`M108` takes no argument in the handler. It samples three digital input bits and returns them as decimal 0/1 fields separated by underscores: mask `0x04` at peripheral base `0x40010800`, then masks `0x02` and `0x04` at `0x40010c00`. The MCU memory map is consistent with STM32F1 GPIO blocks, but the exact part and board-level pin functions have not been confirmed. The response shape is statically established; these bit values have not been captured live.

For the observed `M42 P36 M1 S0/S1` forms, the handler replies `M42_OK_LED` and changes an internal output-state byte. Depending on its model/configuration branch, it writes 100 or 0 to a timer-like peripheral register, or writes mask `0x180` to the GPIO set/reset registers at base `0x40010800`. This records the firmware writes without assigning a UV enable pin or inferring active polarity. PrinterUI's `openLight`/`closeLight` names associate S0/S1 with those UI actions, but a passive capture and board trace are still needed to establish physical behavior.

`M410` replies `M410_OK1` before its state-dependent body. When the layer busy flag is set, one path clears event/state fields and both `M678` busy bytes; other branches clear or set motion/timer state based on the parsed S value and motion mode. This is consistent with a stop/reset control family, but the exact S0/S1/S2 mapping is not proven by the binary path alone. No `M410` command was sent.

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

The PrinterUI's `doExposure` method sends `M114` immediately before calling `openLight`; the MCU event bit consumed by `M114` is set at the end of the `M678` worker path. This cross-binary ordering strongly suggests that `M114_DELATLIGHT_OVER` is an MCU-to-UI phase gate before light exposure, but no passive UART trace during a layer has confirmed which `M114` reply the UI accepts in that moment. The worker's numbered states describe internal phases, not layer numbers or percentages. Exact timing units, event-object ownership, motor/light operations performed in each phase, and the point where the display path gates the MCU remain unresolved. No `M678` command was sent; these conclusions come from the shipped binary and PrinterUI templates.

## STM32 ROM bootloader protocol

The Linux rootfs includes `stm32flash 0.5`. The `stm32_update` startup script controls the H616-side BOOT0 and RESET lines, then invokes `stm32flash` on the same UART to identify and write STM32 flash at `0x08000000`. This is separate from the printer's ASCII/G-code-like application protocol. ST documents the USART system bootloader in [AN3155](https://www.st.com/resource/en/application_note/an3155-usart-protocol-used-in-the-stm32-bootloader-stmicroelectronics.pdf) and boot-mode selection in [AN2606](https://www.st.com/resource/en/application_note/an2606-introduction-to-system-memory-boot-mode-on-stm32-mcus-stmicroelectronics.pdf).

The updater's `stm32flash` information command omits `-b`, so the utility's own default is 57,600 baud; the normal application UART is restored to 115,200 after the update path. The exact STM32 part and its ROM bootloader revision are not known, so its supported USART pins, ROM commands, and read-protection state are not established. `stm32flash` supports read (`-r`) as a utility capability, but Creality's startup script does not invoke it and we did not attempt a read.

## Still needed for a complete protocol spec

- A passive UART capture during idle, status query, manual Z movement, light control, and a harmless temperature query.
- Board photographs or electrical probing to identify the UART connector, logic levels, MCU marking, reset/BOOT0 routing, and the display connectors.
- A longer but less perturbative passive UART capture for periodic idle queries and print-layer synchronization. Launch-time `strace -f` works where attaching to the existing PID is denied, but tracing all startup file I/O perturbs this UI build. A second reader on `/dev/ttyS2` is not safe because it could consume PrinterUI replies.
- The remaining `M678` physical semantics and units, exact timer tick rate, how the display path gates MCU phases, `M410`/`M355` state semantics, and the complete direct `MengTool` command path.
- The full STM32 interrupt/peripheral/register map and resolved names for the many remaining functions. Ghidra pseudocode, the 257-function index, and string cross-references are available privately; this public project does not redistribute the vendor image or pseudocode.
