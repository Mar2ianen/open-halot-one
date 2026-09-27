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

The UART is the STM32 control/status channel: it carries the ASCII-like commands and line replies described below. CL60 layer bitmaps use a separate H616 video-output path. PrinterUI's active profile creates the generic `CreateVideoOutport`/ION backend, transforms the 1620×2560 source layer to 540×2560, and the running kernel shows that mode entering the RK628 HDMI receiver before MIPI DSI1. Thus the large exposure bitmap is not framed into the 100-byte UART command protocol. The exact in-memory pixel packing and conversion into monochrome panel columns remain open.

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

## STM32 application commands found in PrinterUI and `V1-01.bin`

The following strings and call sites are present in both sides of the control link. Some are recognized command families, not a complete protocol specification; payload units and edge cases still need live traces or further firmware analysis.

| Family | Observed command/string | Current interpretation |
|---|---|---|
| Version/model handshake | `V114 `, `MODELS:`, `MODELS `, `GET MODELS:%s OK` | PrinterUI sends `V114 ` and later a `MODELS:` request; the image contains `SWV1.89`. The exact complete request/reply transcript is inferred from strings and call order, not captured. |
| Z axis | `G0 Z500 F… D1 S1/S0 H…`; `G0 Z… F… D0 S1/S0 H…` | UI builders label the first command “up” and the second “down”; `F` is a speed-like parameter, `H` is the configured helical pitch, and `S` selects the external/non-external motor variant. |
| Position/status | `M114`, `M113`, `M108`, `M410 S0/S1/S2` | Used by status, homing, stop, or busy-state paths; exact `M410` submode meanings are not fully recovered. |
| Layer operation | `M678 Z… U… D… T… P… M… L…` | Layer/job command family present in the MCU image and UI strings. |
| Temperature | `M105`, `M105 T… ON`, `M105 T OFF`; reply template `M105_TA…_TB…` | Temperature query/report and on/off control paths. |
| UV/light | `M42 P36 M1 S0` / `M42 P36 M1 S1`; `M355 P1 C…`; `M355` | UI functions name the `M42` calls `openLight`/`closeLight`; the firmware also contains `M355` and `M355_OK`. |
| Fans/outputs | `M106`, `M107`, `M106 P1 S255`, `M107 P1 S0/S255` | Fan/output control strings; output labels and electrical mapping remain unconfirmed. |
| Other | `M800`, `M800_OK`, `M42_OK_LED` | Present in firmware strings; purpose not yet determined. |

The MCU image contains response/status strings such as `M114_OK`, `M114_Busy`, `M113_OK`, `M410_OK1`, `M678_Busy`, `M105_OK_ON`, and `M105_OK_OFF`. Their exact state machines and all numeric parameter units remain open.

## STM32 ROM bootloader protocol

The Linux rootfs includes `stm32flash 0.5`. The `stm32_update` startup script controls the H616-side BOOT0 and RESET lines, then invokes `stm32flash` on the same UART to identify and write STM32 flash at `0x08000000`. This is separate from the printer's ASCII/G-code-like application protocol. ST documents the USART system bootloader in [AN3155](https://www.st.com/resource/en/application_note/an3155-usart-protocol-used-in-the-stm32-bootloader-stmicroelectronics.pdf) and boot-mode selection in [AN2606](https://www.st.com/resource/en/application_note/an2606-introduction-to-system-memory-boot-mode-on-stm32-mcus-stmicroelectronics.pdf).

The updater's `stm32flash` information command omits `-b`, so the utility's own default is 57,600 baud; the normal application UART is restored to 115,200 after the update path. The exact STM32 part and its ROM bootloader revision are not known, so its supported USART pins, ROM commands, and read-protection state are not established. `stm32flash` supports read (`-r`) as a utility capability, but Creality's startup script does not invoke it and we did not attempt a read.

## Still needed for a complete protocol spec

- A passive UART capture during idle, status query, manual Z movement, light control, and a harmless temperature query.
- Board photographs or electrical probing to identify the UART connector, logic levels, MCU marking, reset/BOOT0 routing, and the display connectors.
- Full call-site mapping of the direct `MengTool` path and the parameter semantics of `M678`, `M410`, `M355`, and the M42 outputs.
- A decoded STM32 image with function boundaries, peripheral/register map, and command-handler cross-references. The bundled image is retained privately; this public project does not redistribute it.
