# Open Resin Alliance port plan: HALOT-ONE CL-60

## Goal

Port the existing Open Resin Alliance print stack to the Creality HALOT-ONE CL-60: use its Allwinner H616 as the host, its STM32 as the motion/UV controller, and support both the operator touchscreen and the monochrome exposure panel. This is a device-support effort for the existing ORA projects, not a new ORA firmware that can be flashed as-is.

The current public project is [open-halot-one](https://github.com/Mar2ianen/open-halot-one). Any contribution to ORA should be coordinated with the ORA maintainers and follow the license of the specific target repository; ORA's projects are licensed individually.

## Fit with the existing ORA stack

- [Odyssey](https://github.com/Open-Resin-Alliance/Odyssey) is a printer backend/engine. Its current README describes processing Prusa SL1 jobs for Apollo controllers and the Prometheus MSLA printer. Its YAML configuration includes a serial device, baud rate, display framebuffer, and printer G-code commands. The current `main` includes a generic pixel-group packer with configurable per-sample bit widths, left/right pad bits, and byte-order inversion; the Athena2 profile uses eight 3-bit samples plus 8 pad bits in each 32-bit framebuffer group. This is reusable packing logic, but its framebuffer sink and Athena2 group layout do not implement CL-60 output. HALOT's confirmed userspace transform packs three adjacent 8-bit source samples as `[sample[2], sample[1], sample[0], 0xff]`, then submits a 540×2560 BGRA frame through the vendor H616 HDMI → RK628 → MIPI path. HALOT support therefore still needs a device backend/profile and that distinct output path; its command protocol and panel path are not plug-compatible by assumption. See Odyssey's [`display.rs`](https://github.com/Open-Resin-Alliance/Odyssey/blob/f7c8e68537848eabf3be09841a924d42b9a82403/src/display.rs) and [Athena2 config](https://github.com/Open-Resin-Alliance/Odyssey/blob/f7c8e68537848eabf3be09841a924d42b9a82403/resources/configs/athena2.yaml).
- [Orion](https://github.com/Open-Resin-Alliance/Orion) is a Flutter frontend. Its current Linux build instructions target ARM64 and its deployment notes focus on Raspberry Pi/flutter-pi. It needs to be built and integrated for this H616 system, or replaced by a small HALOT-specific UI during bring-up.
- [DragonFruit](https://github.com/Open-Resin-Alliance/DragonFruit) and [LumenFormat](https://github.com/Open-Resin-Alliance/LumenFormat) are the slicer and open job-format projects. LUMEN v1.0 is published. The latest checked LumenFormat `main` (`109d7d444c9714d8d41f3e3e0ddb47e21eaa1eda`, rechecked 2026-09-30) says Odyssey consumes LUMEN, but the checked Odyssey `main` (`f7c8e68537848eabf3be09841a924d42b9a82403`) has no LUMEN dependency and accepts only `.sl1` in [`src/printfile.rs`](https://github.com/Open-Resin-Alliance/Odyssey/blob/f7c8e68537848eabf3be09841a924d42b9a82403/src/printfile.rs). The checked DragonFruit `main` (`f6c7a20043c16c54d6263c6bb7e308a5f6d27377`) also lacks the Lumen submodule its README describes. Treat both integrations as undocumented/unverified in those snapshots. LumenFormat's Rust reader is reusable format code, but a CL-60 adapter must handle per-sector masks/timing and either implement the extra cure-and-move cycle per sector or reject multi-sector files; HALOT also needs its own image conversion, exposure sink, and scheduler. Agree with ORA on the job format and adapter boundary; do not assume the stock Creality format or Odyssey's `.sl1` path already covers HALOT jobs.

The ORA contact page directs project requests to the relevant repository's GitHub issues and lists Discord for community coordination. No request has been sent by this project.

## What is already known on this printer

| Area | Confirmed | Still open for the port |
|---|---|---|
| Host | Allwinner H616, TinaLinux, vendor Linux `4.9.170`, U-Boot `2018.05` | A HALOT board DTS, supported boot-image packaging, active/fallback boot path, and a proven rollback route |
| Operator UI | Display engine reports an `800x480@59` RGB24 screen; touch controller appears at I²C3 `0x38` | Panel timing/power details for a mainline DTS; mapping and calibration of all touch events under the new UI |
| Exposure display | Active path is H616 HDMI output at 540×2560 → RK628 HDMI RX at I²C2 `0x50` → MIPI DSI1 at 4 × 840 Mb/s; `dsi_err=0`. Static `CL60R` type-1 timing lookup selects 540×2560 at 112 MHz, separately from the HDMI-path `src`/`dst` report. The I²C0 `dlp1438` driver rejects this product (`-22`). | Effective runtime DSI timing override, physical FPC trace, exact pixel-to-column mapping, layer-to-VSYNC synchronization, error recovery, and a mainline RK628/panel driver |
| Control MCU | PrinterUI and the startup updater use `/dev/ttyS2`; application link is 115200 8N1; fixed 101-byte framing; `M678` storage/state flow; physical units `Z` (mm), `U` (mm/s), `D` (dead); `L` Stefan adhesion settling formula ($M/10 + 100 \times \lfloor\text{avg}(L)/1200\rfloor$); `P`/`M` ms units; `M410 S0/S1/S2` stop/abort semantics; `PA5` upper optical endstop; active internal motor 1,600 steps/mm on TIM4 PB6/PB3. | Exact display-to-MCU gate; electrical levels and board connector wiring for PC13–PC15; MengTool endpoint/`ASK_DATA` reply format; clean wire timing |
| Firmware update | The vendor startup script can toggle BOOT0/reset and call `stm32flash` to write the bundled Cortex-M image | Exact STM32 part/read-protection state and safe recovery behavior; do not use the update sequence as a test command |
| Display userspace | Stock PrinterUI expects vendor interfaces including `/dev/disp` and `/dev/ion` | Replace/adapt these consumers for DRM/KMS and modern buffer allocation, or keep the vendor kernel while proving the ORA userspace stack |

The complete device and package notes are in [the hardware map](hardware-map.md), [the software map](software-map.md), [the protocol map](protocols.md), and [the firmware/boot analysis](firmware-update.md).

## Local Odyssey prototype

As of 2026-09-30, a local Odyssey checkout based on upstream commit `f7c8e68537848eabf3be09841a924d42b9a82403` contains an inert HALOT protocol module on branch `codex/halot-cl60-inert-prototype`. The upstream `main` heads were rechecked on 2026-09-30: Odyssey `f7c8e68537848eabf3be09841a924d42b9a82403`, DragonFruit `f6c7a20043c16c54d6263c6bb7e308a5f6d27377`, LumenFormat `109d7d444c9714d8d41f3e3e0ddb47e21eaa1eda`, and Orion `65bba7a87c8547e5e8fe3aec58b0adeaa2b087d9`. Odyssey's production executable still registers only `.sl1`, while DragonFruit's checked tree lacks the Lumen submodule described by current LumenFormat documentation. The local work is not pushed upstream.

The prototype exposes fixed-frame encoding, raw `M678` token formatting, incremental reply parsing, an observation-only layer cycle, sanitized UART replay, and a pure one-layer-prefetch scheduler. Its CXDLP v2/v3 reader supports borrowed input and owned buffers, expands vertical runs to dimensioned Gray8 layers, and builds a candidate source-triplet-to-BGRA buffer without a display sink. A private printer-produced v2 job recovered from the post-print snapshot has 1,591 layers and 1,647,513 run records; all coordinates validate, the duplicate area tables match, and its layer count/areas correlate with the completed 1,591-cycle UART trace. A schedule-aware full-job dry run formed all layer plans and synthetic status cycles. This single-job result is not independent format conformance. The candidate frame does not establish physical panel-column order or synchronization. The production print server does not select these modules; only the offline `halot-inspect` tool uses the parser/planner, and no module has serial, framebuffer, GPIO, motor, or UV access.

The source checkout's GPL-3.0 license was checked before adding the modules. The previous recorded baseline passed `cargo fmt --check` and `cargo check --offline`; today's owned-buffer change has not been build-checked. No automated tests or printer commands were run for this update. The local integration note describes why a command-only `HardwareControl` implementation would not preserve the CL-60's per-layer image/UART order. A read-only source audit found that Odyssey currently accepts SL1 jobs and its `Frame`/framebuffer path loses the dimensions and sample layout needed for the HALOT image route; the production job path still needs HALOT-specific integration.

The installed 2.303.1 `lcdPrint` path has a one-layer decode prefetch: it submits image *i*, sends `M678` for *i*, starts parsing layer *i+1*, then waits for the current `M114_OK` before the next loop submits another frame. The pure local scheduler now models that ordering, but it does not own a prefetched raster or run concurrent decode and I/O tasks. This is an overlap opportunity for the ORA scheduler, not permission to overlap display submissions and controller transactions. The active host reuses one ION buffer address for frame copies; potential tearing during scanout is an inference that needs timing evidence, not an observed defect.

## Kernel feasibility

**A newer kernel is technically feasible at the SoC level, but a complete HALOT port is not demonstrated yet.** The current mainline H616 device tree describes ordinary SoC blocks and the disabled Mali GPU node, but no display-engine or HDMI nodes. The sun4i DRM mixer driver has an H616 DE33 variant, while the HDMI PHY match table currently ends at H6 and has no H616 entry. Recent HDMI-node discussion confirms that DE33 mixer support alone is insufficient and that the current H616 display topology proposal was rejected as an inaccurate hardware description. The operator RGB panel therefore needs a board-derived DTS plus working H616 display/TCON support; the resin panel additionally depends on the vendor RK628 path, for which the inspected mainline tree has no driver. The live device tree and stock modules remain the best hardware reference. See upstream [H616 DTS](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/allwinner/sun50i-h616.dtsi), [DE33 mixer driver](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/sun4i/sun8i_mixer.c), [HDMI PHY driver](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/sun4i/sun8i_hdmi_phy.c), and the [September 2026 H616 HDMI review](https://lists.infradead.org/pipermail/linux-arm-kernel/2026-September/1169049.html). Rockchip's [RK628 U-Boot driver commit](https://github.com/rockchip-linux/u-boot/commit/ab3bc87) provides a GPL reference for HDMI-RX, DSI, and panel programming, but it is not a drop-in Allwinner Linux or mainline DRM driver.

Panfrost's upstream model table recognizes Mali-G31 (`GPU ID 0x7003`, revision 1.0), which is promising for an adapted replacement UI built against Mesa. The stock vendor driver reports `Mali-G31 ... 0x7093`; its ID encoding is not directly comparable to Panfrost's parsed model/revision fields, so a mainline bring-up must confirm the exact GPU ID and revision. Panfrost cannot run the stock PrinterUI's proprietary Kbase `/dev/mali0` ABI. Even with Panfrost, the printer's video route still needs H616 HDMI/TCON and RK628 bridge support. The practical near-term route is newer userspace on the existing vendor kernel, preserving its known-working `/dev/disp`, `/dev/ion`, HDMI, and RK628 drivers while adapting the ORA application to the device's armhf runtime. See the upstream [Panfrost GPU table](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/panfrost/panfrost_gpu.c).

The stock boot path uses a vendor U-Boot and Android-style kernel partitions. The exact installed TOC1 package and the vendor `awuboot` write offsets are mapped: it clears 1 MiB at `0x012a6000`, then writes the package at `0x01004000`. The saved environment names `boot`/`bootm`, but its `setargs_nand` and `setargs_mmc` root values do not match the running kernel's `/dev/mmcblk0p6`; the exact U-Boot path that produced the live command line remains unresolved. Before writing any boot or rootfs image, identify the active environment copy and establish a tested recovery route. Secure-boot acceptance and rollback remain unverified in [the boot analysis](firmware-update.md).

The least invasive software milestone is to build an ORA-compatible backend for the ABI and libraries available in the existing rootfs, then run it from the writable overlay while leaving the stock kernel, boot partitions, STM32, and vendor UI recoverable. This isolates print-protocol and file-format work from mainline-kernel bring-up. It may still require a compatible binary target or a small rootfs for the host architecture.

On a newer kernel, the existing UI's vendor `/dev/disp` and `/dev/ion` assumptions need a replacement. Mainline's normal graphics and shared-buffer path is DRM/KMS plus dma-buf heaps; the HALOT display output code must be adapted to that model, unless the exposure-panel path proves to be a separate supported device.

## Suggested milestones

### 1. Define the ORA integration boundary

- Ask ORA maintainers whether HALOT-specific code belongs in Odyssey, a printer-adapter repository, or a separate H616 host project.
- Agree on the job format and division between the print engine, serial/control adapter, exposure-image output, and Orion UI. The local CXDLP v2/v3 reader has been checked against one private printer job and its trace correlation, but it is not integrated with Odyssey or a general ORA job format. A separate static map of PioCreat's CXLINE v2 writer/reader exists, but there is no `.cxline` fixture and no CXLINE parser. Neither Creality format should become the ORA format by default; see the [CXLINE v2 static map](cxline-v2-format.md).
- Keep `open-halot-one` as the hardware research and bring-up record; submit implementation code only after the target repo and license are agreed.

### 2. Complete the hardware/software interface map

- **Closed protocol/hardware cases:**
  - `M678 L` physical event: dynamic settling threshold ($M/10 + 100 \times \lfloor\text{avg}(L)/1200\rfloor$ ticks) for Stefan adhesion compensation. State 8 asserts PC15 active-low hardware UV enable, sends DLPC347x I²C `0x36 0x52 0x04` (Blue/UV ON), and sets bit 1 on EventGroup `0x2000001c` (`M114_DELATLIGHT_OVER`).
  - Physical motor units: `Z` in mm (scaled by 100 on parse), `U` in mm/s, `D` is dead parameter. Active `CL60` internal motor (`S1` / `TIM4` on PB6/PB3 via `FUN_08000fb8`) resolution is **`1,600.0` steps/mm** (200 full steps/rev, 2 mm pitch $\implies$ 100 full steps/mm $\times$ 1/16 microstepping; acceleration ramp divisor $64/H = 32$; timer period $\text{ARR} = 5000 / U$). Alternate external motor (`S0` / `TIM2` on PB8/PB9) resolution is `12,800.0` steps/mm (1/128 microstepping; ramp divisor $256/H = 128$; $\text{ARR} = 24,000,000 / (12800 \times U)$). Lead screw pitch is standard T8x2 ($H = 2\text{ mm}$ from `halotMachine.xml`).
  - Stop/abort semantics: `M410 S0` (instant hard stop), `M410 S1` (1600-step deceleration ramp stop), `M410 S2` (print abort: TIM3 disabled, UV light forced OFF via I²C `0x52 0x00` and PC15=1, TIM1 disabled, print task suspended). All acknowledge with `M410_OK1\n`.
  - Homing and motion kinematics: `G0 Z%1 F%2 D%3 S%4 H%5 ` (D1=Up towards top endstop, D0=Down towards vat, S1=internal TIM4 / S0=external TIM2, H=HelicalPitch = 2 mm). Optical limit switch on **PA5 is strictly at the TOP of the Z-axis (upper limit switch)**; upward motion (`D1`) halts when `PA5 == 1` via a 1,600-step deceleration ramp on active TIM4 (or instant zeroing on TIM2), emitting `M114_OK1\n`. Downward motion (`D0`) ignores PA5 and travels downward to the vat (`LevelHeight = 170\text{ mm}`, 272,000 steps at 1,600 steps/mm). Standard `G28` is not used.
  - Startup I²C: `0x36 0x54 [30 0c 30 0c 30 0c]` matches TI DLPC347x current command fingerprint (current calibration and physical driver validation open).
- Keep the operator UI (`/dev/fb0` 800×480) and exposure display (ION → `/dev/disp` → HDMI → RK628 → MIPI DSI1 540×2560) strictly separate.
- Capture only passive serial traffic first; do not probe by sending motion or UV commands during protocol discovery.

### 3. Build a host-side HALOT adapter and verify the Three Acceptance Boundaries

The HALOT architecture couples layer motion, hydrodynamic settling delay, UV exposure, and lift into a single atomic controller transaction (`M678`). To build a faithful port without breaking this state machine, three core boundaries must be satisfied:
1. **Physical Display Submission & Synchronization:** Guarantee that subpixel-triplet BGRA frames (540×2560) written to ION and applied via `/dev/disp` (ioctl `0x42`/`0x43`) are fully latched by the RK628 bridge before STM32 transitions to exposure (`M114_DELATLIGHT_OVER`).
2. **Safe M678 Layer Transaction & Fault Contract:** Wrap `M678` $\rightarrow$ `M114` polling $\rightarrow$ `M114_DELATLIGHT_OVER` $\rightarrow$ `M114_OK` into a single atomic transaction. Enforce safe cancellation/pause via `M410 S...` to ensure UV is physically deasserted on host fault or serial timeout.
3. **Odyssey Integration Seam (`HalotTransactionBackend`):** Integrate with Odyssey's job lifecycle using a dedicated layer transaction boundary rather than Odyssey's split `move_z()`, `start_curing()`, `stop_curing()` primitives.

### 4. Near-Term Milestone: `halot-inspect` ARMv7 and `HalotTransport` architecture

Prior to implementing an active actuator FSM, deploy an extended `halot-inspect` binary to the H616 target (TinaLinux procd runtime):
- **ABI & Runtime verification:** Verify ARMv7 hard-float ABI and glibc/dynamic linker compatibility under TinaLinux procd environment.
- **Serial link verification (Passive):** Open `/dev/ttyS2` in passive read-only mode to verify banner/handshake reception without transmitting unverified bytes.
- **Display allocation probe:** Probe `/dev/ion` and `/dev/disp` ioctl interfaces; allocate and display a safe blank/test pattern with UV physically guaranteed off.
- **On-device decoding benchmark:** Benchmark on-device CXDLP v2/v3 lazy decoding performance on Cortex-A53 cores.

#### `HalotTransport` Architecture
To integrate cleanly with Odyssey's async runtime (`tokio-serial`), implement `HalotTransport` as an encapsulation layer:
- `encode_101_byte_frame(cmd: &str) -> [u8; 101]`: Applies 96-byte padding, delimiter `[0x55, 0x55, 0x55, 0x55]`, and trailing `\n`.
- `incremental_line_decoder()`: Decodes lines asynchronously, identifying `M114_Busy_*`, `M114_DELATLIGHT_OVER`, `M114_OK`, and `M114_OK1`.
- `startup_handshake()`: Queries MCU version (`V114`), models (`GET MODELS`), and performs top reference homing (`G0 Z170 F3 D1 S1 H2`).
- `m678_transaction()`: Atomic layer transaction orchestrating display latching, M678 execution, M114 polling, and UV-on synchronization.
- `cancel_transaction()`: Emergency abort via `M410 S2`, turning off UV physically, followed by safe top carriage lift.
- **Deployment Lifecycle:** TinaLinux uses OpenWrt-style `procd` with SquashFS + ext4 overlay. Packaging and running Odyssey requires an `/etc/init.d/odyssey` procd service script with clean, mutual-exclusion process management (never `killall -9`) ensuring guaranteed UV-off state on handover.

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
