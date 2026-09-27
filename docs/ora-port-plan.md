# Open Resin Alliance port plan: HALOT-ONE CL-60

## Goal

Port the existing Open Resin Alliance print stack to the Creality HALOT-ONE CL-60: use its Allwinner H616 as the host, its STM32 as the motion/UV controller, and support both the operator touchscreen and the monochrome exposure panel. This is a device-support effort for the existing ORA projects, not a new ORA firmware that can be flashed as-is.

The current public project is [open-halot-one](https://github.com/Mar2ianen/open-halot-one). Any contribution to ORA should be coordinated with the ORA maintainers and follow the license of the specific target repository; ORA's projects are licensed individually.

## Fit with the existing ORA stack

- [Odyssey](https://github.com/Open-Resin-Alliance/Odyssey) is a printer backend/engine. Its current README describes processing Prusa SL1 jobs for Apollo controllers and the Prometheus MSLA printer. Its YAML configuration includes a serial device, baud rate, display framebuffer, and printer G-code commands. HALOT support would need a device backend/profile and an image-output path; its command protocol and panel path are not plug-compatible by assumption.
- [Orion](https://github.com/Open-Resin-Alliance/Orion) is a Flutter frontend. Its current Linux build instructions target ARM64 and its deployment notes focus on Raspberry Pi/flutter-pi. It needs to be built and integrated for this H616 system, or replaced by a small HALOT-specific UI during bring-up.
- [DragonFruit](https://github.com/Open-Resin-Alliance/DragonFruit) and [LumenFormat](https://github.com/Open-Resin-Alliance/LumenFormat) are the slicer and open job-format projects. Agree with ORA on the target job format; do not assume that the stock Creality job format or the current Odyssey `.sl1` path already covers HALOT jobs.

The ORA contact page directs project requests to the relevant repository's GitHub issues and lists Discord for community coordination. No request has been sent by this project.

## What is already known on this printer

| Area | Confirmed | Still open for the port |
|---|---|---|
| Host | Allwinner H616, TinaLinux, vendor Linux `4.9.170`, U-Boot `2018.05` | A HALOT board DTS, supported boot-image packaging, active/fallback boot path, and a proven rollback route |
| Operator UI | Display engine reports an `800x480@59` RGB24 screen; touch controller appears at I²C3 `0x38` | Panel timing/power details for a mainline DTS; mapping and calibration of all touch events under the new UI |
| Exposure display | Active path is H616 HDMI output at 540×2560 → RK628 HDMI RX at I²C2 `0x50` → MIPI DSI1 at 4 × 840 Mb/s; `dsi_err=0`. This matches PrinterUI's 1620-to-540 layer compression. The I²C0 `dlp1438` driver rejects this product (`-22`). | Physical FPC trace, exact pixel-to-column mapping, timing controls, layer synchronization, error recovery, and a mainline RK628/panel driver |
| Control MCU | PrinterUI and the startup updater use `/dev/ttyS2`; application link is 115200 8N1; fixed framing, `M678` storage/state flow, `M113`/`M114`, `M108` input bits, and static `M42`/`M355`/`M410` behavior are documented in [the protocol map](protocols.md) | Physical meaning/units of layer fields, timer units, exact display-to-MCU gate, output pin mapping, remaining `M106`/`M107` and MengTool semantics, and a passive wire trace |
| Firmware update | The vendor startup script can toggle BOOT0/reset and call `stm32flash` to write the bundled Cortex-M image | Exact STM32 part/read-protection state and safe recovery behavior; do not use the update sequence as a test command |
| Display userspace | Stock PrinterUI expects vendor interfaces including `/dev/disp` and `/dev/ion` | Replace/adapt these consumers for DRM/KMS and modern buffer allocation, or keep the vendor kernel while proving the ORA userspace stack |

The complete device and package notes are in [the hardware map](hardware-map.md), [the software map](software-map.md), [the protocol map](protocols.md), and [the firmware/boot analysis](firmware-update.md).

## Kernel feasibility

**A newer kernel is technically feasible at the SoC level, but a complete HALOT port is not demonstrated yet.** The upstream Linux tree has H616 device-tree support, including the H616 DE33 display mixer binding. That is evidence that the CPU and some standard peripherals can run with mainline drivers; it is not a board description for this printer or proof that the exposure panel is supported.

The stock boot path uses a vendor U-Boot and Android-style kernel partitions. The exact installed TOC1 package and the vendor `awuboot` write offsets are mapped: it clears 1 MiB at `0x012a6000`, then writes the package at `0x01004000`; the normal environment path boots `p5` as an Android boot image. Before writing any boot or rootfs image, identify the active environment copy and establish a tested recovery route. Secure-boot acceptance and rollback remain unverified in [the boot analysis](firmware-update.md).

The least invasive software milestone is to build an ORA-compatible backend for the ABI and libraries available in the existing rootfs, then run it from the writable overlay while leaving the stock kernel, boot partitions, STM32, and vendor UI recoverable. This isolates print-protocol and file-format work from mainline-kernel bring-up. It may still require a compatible binary target or a small rootfs for the host architecture.

On a newer kernel, the existing UI's vendor `/dev/disp` and `/dev/ion` assumptions need a replacement. Mainline's normal graphics and shared-buffer path is DRM/KMS plus dma-buf heaps; the HALOT display output code must be adapted to that model, unless the exposure-panel path proves to be a separate supported device.

## Suggested milestones

### 1. Define the ORA integration boundary

- Ask ORA maintainers whether HALOT-specific code belongs in Odyssey, a printer-adapter repository, or a separate H616 host project.
- Agree on the job format and division between the print engine, serial/control adapter, exposure-image output, and Orion UI.
- Keep `open-halot-one` as the hardware research and bring-up record; submit implementation code only after the target repo and license are agreed.

### 2. Complete the hardware/software interface map

- Finish the residual static STM32 cases: `M106`/`M107` value effects, all `M410` branches, MengTool's direct serial path, and physical meanings for the recovered GPIO/PWM operations.
- Reproduce PrinterUI's 1620-to-540 layer packing and confirm how RGB channels map to monochrome columns; capture image/output timing relative to STM32 exposure commands.
- Keep the operator UI and exposure display as separate pipelines. The exposure route is traced through the RK628 to DSI1, while the physical panel FPC and exact pixel mapping remain open.
- Capture only passive serial traffic first; do not probe by sending motion or UV commands during protocol discovery.

### 3. Build a host-side HALOT adapter

- Define a testable transport interface for the known `/dev/ttyS2` framing and response parsing.
- Implement the HALOT command adapter for Odyssey, initially against a mock serial endpoint and synthetic exposure frames.
- Add the agreed ORA job format and layer scheduler, then verify sequence ordering, cancellation, timeouts, and recovery from malformed replies without actuating the printer.

### 4. Bring up ORA userspace on stock kernel

- Determine the stock userspace ABI, available runtime libraries, service manager, and graphics interfaces.
- Build the backend for the actual target ABI; expose it as a service with explicit safe startup/shutdown behavior.
- Test Orion on the operator display as a separate task. Keep the existing Creality UI launchable until the replacement is stable.
- Keep the operator UI and exposure output separate: `/dev/fb0` is the 800×480 touch UI, while the current exposure path runs through the H616 HDMI output and RK628 DSI1 bridge.

### 5. Port the board to mainline Linux

- Create a board DTS for memory, eMMC, power regulators, clocks, GPIOs, UART2, operator RGB panel/touch, and all required buses.
- Verify the standard operator panel with DRM/KMS and touchscreen input.
- Implement or upstream the HALOT exposure-panel path, including RK628/CXSW dependencies and buffer/timing semantics.
- Port any remaining vendor-only services needed for temperature/fan control and safe shutdown.
- Package the kernel/rootfs for the actual U-Boot and prove boot/recovery on a spare image or recoverable boot target before replacing the known-good system.

### 6. Acceptance for normal printing

The port is not ready for normal use until it can repeatedly:

- cold boot to the replacement UI and retain a documented rollback path;
- import the agreed open job format and report correct layer count, dimensions, and exposure settings;
- home and move Z with correct limits, direction, speed, and position reporting;
- show the operator UI and touchscreen reliably;
- render and synchronize monochrome exposure layers on the correct physical panel;
- keep UV off on boot, cancellation, fault, shutdown, and loss of the host/backend;
- complete a full job while handling pause, resume, cancel, serial timeout, and restart safely.

## Overall assessment

The host SoC is a reasonable Linux target and the STM32 control link is accessible from Linux. The port is feasible as a multi-layer integration project. The exposure stream is now traced through the H616 HDMI output and RK628 DSI1, but its channel-to-column mapping and full timing contract still need work. Safe boot/recovery and the full contract between Odyssey's layer engine and the HALOT controller remain major unknowns. Start with the HALOT adapter and file/control path on the stock kernel; take on a newer kernel after the printer-specific display and recovery paths are understood.
