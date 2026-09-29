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
| Exposure display | Active path is H616 HDMI output at 540×2560 → RK628 HDMI RX at I²C2 `0x50` → MIPI DSI1 at 4 × 840 Mb/s; `dsi_err=0`. Static `CL60R` type-1 timing lookup selects 540×2560 at 112 MHz, separately from the HDMI-path `src`/`dst` report. The I²C0 `dlp1438` driver rejects this product (`-22`). | Effective runtime DSI timing override, physical FPC trace, exact pixel-to-column mapping, layer-to-VSYNC synchronization, error recovery, and a mainline RK628/panel driver |
| Control MCU | PrinterUI and the startup updater use `/dev/ttyS2`; application link is 115200 8N1; fixed framing, `M678` storage/state flow, `M113`/`M114`, `M108` inputs, static `M42`/`M355`/`M410`/`M106`/`M107` paths, and raw `reboot`/`test` ISR exceptions are documented in [the protocol map](protocols.md) | Physical meaning/units of `Z/U/D`, exact STM32 timer use of `P/M`, operational use of `L`, display-to-MCU gate, board mapping of GPIO aliases and `M410` branches, MengTool endpoint/`ASK_DATA` reply format, and clean wire timing |
| Firmware update | The vendor startup script can toggle BOOT0/reset and call `stm32flash` to write the bundled Cortex-M image | Exact STM32 part/read-protection state and safe recovery behavior; do not use the update sequence as a test command |
| Display userspace | Stock PrinterUI expects vendor interfaces including `/dev/disp` and `/dev/ion` | Replace/adapt these consumers for DRM/KMS and modern buffer allocation, or keep the vendor kernel while proving the ORA userspace stack |

The complete device and package notes are in [the hardware map](hardware-map.md), [the software map](software-map.md), [the protocol map](protocols.md), and [the firmware/boot analysis](firmware-update.md).

## Local Odyssey prototype

On 2026-09-28, a local Odyssey checkout at upstream commit `f7c8e68537848eabf3be09841a924d42b9a82403` received an inert HALOT protocol module on branch `codex/halot-cl60-inert-prototype`; a pure in-memory packer for the statically recovered source-triplet-to-BGRA transform and a CXDLP v3 reader were added on 2026-09-29. The work is not pushed upstream. The modules expose fixed-frame encoding, raw `M678` token formatting, incremental reply parsing, an observation-only layer cycle, sanitized UART replay, CXDLP vertical-run decoding to Gray8, and `decode_candidate_panel_frame`, which composes the raster steps while retaining source dimensions and layer metadata. Replay validates ordering and replies without retaining `M678` parameter values. The candidate image buffer is not sent to a display and does not establish physical panel-column order. The CXDLP parser has not been checked against an independent or printer-produced file and is not integrated with Odyssey's `PrintFile` path. Odyssey's executable does not select or call these modules, and they have no serial, framebuffer, GPIO, motor, or UV access.

The source checkout's GPL-3.0 license was checked before adding the modules. The current local source passes `cargo fmt --check` and `cargo check --offline`; no tests or printer commands were run. The local integration note describes the current code seam and why a command-only `HardwareControl` implementation would not preserve the CL-60's per-layer image/UART order. A read-only source audit also found that Odyssey currently accepts SL1 jobs and its `Frame`/framebuffer path loses the dimensions and sample layout needed for the HALOT image route; those remain separate port tasks.

The installed 2.303.1 `lcdPrint` path has a one-layer decode prefetch: it submits image *i*, sends `M678` for *i*, starts parsing layer *i+1*, then waits for the current `M114_OK` before the next loop submits another frame. This is an overlap opportunity for the ORA scheduler, not permission to overlap display submissions and controller transactions. The active host reuses one ION buffer address for frame copies; potential tearing during scanout is an inference that needs timing evidence, not an observed defect. The local prototype plans one layer at a time and does not yet model this scheduling.

## Kernel feasibility

**A newer kernel is technically feasible at the SoC level, but a complete HALOT port is not demonstrated yet.** The current mainline H616 device tree describes ordinary SoC blocks and the disabled Mali GPU node, but no display-engine or HDMI nodes. The sun4i DRM mixer driver has an H616 DE33 variant, while the HDMI PHY match table currently ends at H6 and has no H616 entry. Recent HDMI-node discussion confirms that DE33 mixer support alone is insufficient and that the current H616 display topology proposal was rejected as an inaccurate hardware description. The operator RGB panel therefore needs a board-derived DTS plus working H616 display/TCON support; the resin panel additionally depends on the vendor RK628 path, for which the inspected mainline tree has no driver. The live device tree and stock modules remain the best hardware reference. See upstream [H616 DTS](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/allwinner/sun50i-h616.dtsi), [DE33 mixer driver](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/sun4i/sun8i_mixer.c), [HDMI PHY driver](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/sun4i/sun8i_hdmi_phy.c), and the [September 2026 H616 HDMI review](https://lists.infradead.org/pipermail/linux-arm-kernel/2026-September/1169049.html). Rockchip's [RK628 U-Boot driver commit](https://github.com/rockchip-linux/u-boot/commit/ab3bc87) provides a GPL reference for HDMI-RX, DSI, and panel programming, but it is not a drop-in Allwinner Linux or mainline DRM driver.

Panfrost's upstream model table recognizes Mali-G31 (`GPU ID 0x7003`, revision 1.0), which is promising for an adapted replacement UI built against Mesa. The stock vendor driver reports `Mali-G31 ... 0x7093`; its ID encoding is not directly comparable to Panfrost's parsed model/revision fields, so a mainline bring-up must confirm the exact GPU ID and revision. Panfrost cannot run the stock PrinterUI's proprietary Kbase `/dev/mali0` ABI. Even with Panfrost, the printer's video route still needs H616 HDMI/TCON and RK628 bridge support. The practical near-term route is newer userspace on the existing vendor kernel, preserving its known-working `/dev/disp`, `/dev/ion`, HDMI, and RK628 drivers while adapting the ORA application to the device's armhf runtime. See the upstream [Panfrost GPU table](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/panfrost/panfrost_gpu.c).

The stock boot path uses a vendor U-Boot and Android-style kernel partitions. The exact installed TOC1 package and the vendor `awuboot` write offsets are mapped: it clears 1 MiB at `0x012a6000`, then writes the package at `0x01004000`; the normal environment path boots `p5` as an Android boot image. Before writing any boot or rootfs image, identify the active environment copy and establish a tested recovery route. Secure-boot acceptance and rollback remain unverified in [the boot analysis](firmware-update.md).

The least invasive software milestone is to build an ORA-compatible backend for the ABI and libraries available in the existing rootfs, then run it from the writable overlay while leaving the stock kernel, boot partitions, STM32, and vendor UI recoverable. This isolates print-protocol and file-format work from mainline-kernel bring-up. It may still require a compatible binary target or a small rootfs for the host architecture.

On a newer kernel, the existing UI's vendor `/dev/disp` and `/dev/ion` assumptions need a replacement. Mainline's normal graphics and shared-buffer path is DRM/KMS plus dma-buf heaps; the HALOT display output code must be adapted to that model, unless the exposure-panel path proves to be a separate supported device.

## Suggested milestones

### 1. Define the ORA integration boundary

- Ask ORA maintainers whether HALOT-specific code belongs in Odyssey, a printer-adapter repository, or a separate H616 host project.
- Agree on the job format and division between the print engine, serial/control adapter, exposure-image output, and Orion UI. The current local reader is an unverified CXDLP v3 prototype and does not imply that Creality's format should become the ORA format.
- Keep `open-halot-one` as the hardware research and bring-up record; submit implementation code only after the target repo and license are agreed.

### 2. Complete the hardware/software interface map

- Finish residual protocol/UI cases: MengTool's endpoint and `ASK_DATA` response format, the physical meanings of the recovered GPIO/PWM and `M410` register operations, and the controller's use of the `M678 L` value.
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
