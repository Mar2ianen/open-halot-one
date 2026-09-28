# Related Creality resin platforms and open firmware

Research snapshot: 2026-09-28. This page compares the HALOT-ONE CL-60 evidence collected in this repository with public work on other Creality and resin-printer platforms. “Same ecosystem” below means shared file formats, tools, or software patterns; it does not imply pin, MCU, or firmware compatibility.

## What the HALOT evidence actually proves

The inspected CL-60 runs a Creality Linux host and a separate STM32 controller. This project has recovered a fixed-frame host UART protocol, including `M678`, `M114`, `M410`, and status replies, and traced the exposure image path through H616 HDMI and an RK628 bridge to MIPI DSI. Those results are specific to the installed CL-60 image and the one physical unit.

The local 2.303.1 `halotMachine.xml` and `PrinterUI` build contain profiles for multiple Creality machine identifiers, including `CL60`, `CL79` (HALOT-ONE PLUS), `CL89` (HALOT-SKY), `CL89D`, `CL89L`, `CL133`, `CL130`, and other variants. The profiles select different serial model types and display/output configuration. For example, CL60 maps a 1620×2560 source image to 540×2560; CL79 maps 4320×2560 to 1440×2560; CL89 maps 3840×2400 to 1280×2400. All three profiles use the same `LCD` image backend, but specify different pixel sizes and mechanical settings. This proves the **same inspected host application build contains multi-model branches and geometry conversion**, not that the panel electronics or serial controller are identical. The profile field `SendSerialModelType=E` for CL60/CL79 also differs from the separately captured `MODELS:A` handshake command; these must not be conflated as one MCU selector.

There is public evidence for a common Creality file ecosystem: UVtools implements CXDLP/CXDLPV4 and has PrusaSlicer profiles for HALOT-ONE CL-60, HALOT-SKY CL-89, HALOT-LITE CL-89L, HALOT-ONE PLUS CL-79, and HALOT-ONE PRO CL-70. These older models use the CXDLP family in those profiles; the HALOT-MAGE CL-103L profile uses CXDLPV4, while LD-002R/H profiles use CTB. The CL-60 profile declares 1620×2560 display pixels and HALOT-specific file-format tags. UVtools maintainers also report that some CXDLP settings are ignored by the printer in favor of settings stored in the printer UI/firmware. That is useful for the **job-file and slicer layer**, but it does not establish that layer metadata maps one-to-one to the STM32 `M678` parameters.

An independent 2021 HALOT-SKY teardown reports the same broad architecture class as this CL-60: Linux/OpenWrt host, separate STM32F103 motion controller, and HDMI-to-MIPI monochrome-panel bridge. Its identified host SoC is Allwinner H6 and its bridge is Lontium LT6911C; this CL-60 has H616 and RK628 according to our live software/device evidence. This is strong evidence of a shared design pattern in an older HALOT branch, while the changed SoC and bridge are reasons not to assume identical binaries or display protocol.

### Package-level evidence across older HALOT models

The official HALOT-SKY, HALOT-LITE, HALOT-ONE PLUS, and HALOT-ONE PRO download pages resolve their `V1_H2.238.2a2.238.2_C2.238.2_R2.238.2` entries to the **same CDN object**, not four merely similar filenames. The shared archive is 130,822,607 bytes with SHA-256 `b80147dcd1f47d8124bef7b90d9cd6c23ce2af3f16c78a16b7ed737d94c31d57`. Its SWU contains a TinaLinux rootfs and a single `/etc/V1-01.bin` STM32 updater image. The extracted MCU image is 31,248 bytes, SHA-256 `379470dd8afe47b152cabdedcd6c983b1fc112c07d164a18d8d0fbb89677f319`. Thus these four official download entries served the same host and STM32 payload at this release point. That is direct package identity evidence; it does not establish identical mainboards, wiring, panel timing, or safe interchange of the complete printer configuration.

The local HALOT-ONE CL-60 is on a later `2.303.1` generation. The selected component comparison is:

| Component | Shared 2.238.2 package | Local CL-60 2.303.1 | Result |
|---|---|---|---|
| STM32 `/etc/V1-01.bin` | 31,248 B, SHA-256 `379470dd8afe47b152cabdedcd6c983b1fc112c07d164a18d8d0fbb89677f319`, version string `SWV1.821` | 33,236 B, SHA-256 `a950f58db8382c5673b12ee81cd2ebb4833832aa1e226829bd61a1c29d7d7c02`, `SWV1.89` | Firmware changed and is not byte-compatible. Both images retain `M678`, `M114`, and `M410` command/status strings; this establishes vocabulary continuity, not matching handler semantics. |
| `PrinterUI` | 4,377,568 B, SHA-256 `f7256aa2a1401b4aa93a9992c994c7cfad63b0d693138aa8db47c83c1d9b6668` | 4,561,896 B, SHA-256 `a0a0b919bf2a7cc181c120be5e0983624511e25e7eb24406c65e0a6b20d5e8c1` | Different builds; both contain CL60/CL89 model strings, M114 vocabulary, and the `M678 Z%1 U%2 D%3 T%4 P%5 M%6 L%7` template. This demonstrates a shared host-software/interface lineage, not identical runtime behavior for every model. |
| `halotMachine.xml` | 60,211 B, SHA-256 `fe47871811e1df82a120d2f4fd6916c48bca1d63868b0b2b15666ded3b65027c` | 60,611 B, SHA-256 `0854ac93b448d882fc9704516dff0377e699fc2d6897d66ce8cb6dd74aa74fd9` | Changed file; both retain the same CL60/CL60R/CL89 profile labels. |
| RK628 kernel module | `rk628_mod.ko`, 1,933,184 B, SHA-256 `598c16ce536e868d4ca3573775a3c3c6a548cdcf55f23e27d78ed93199844d12` | Same size and SHA-256 | Byte-identical display-bridge driver across the compared generations. |
| Kernel | 13,484,032 B, SHA-256 `6cb3f84433e9a5e18527fca7f61a951aeaee814134055319f4d6179cba9a5422` | 13,484,032 B, SHA-256 `9eb14d93b641fa830c2caac8eac58941edb8da7a159fd10da6d19e9e150bdb22` | Changed; both image manifests report Linux `4.9.170`. |
| Rootfs SquashFS | 111,804,416 B, SHA-256 `01ac30e620b0d59e042da253cf6e527c5572d84fc80786cc28ee3c64e4be46c7` | 111,935,488 B, SHA-256 `4764f1dbb36daf7580061a5c3c90775c64ef06d8a5c25906b8725168d23dfd88` | Changed. |

### STM32 handler comparison

The two MCU images are different builds, but targeted Thumb-code comparisons show more than matching strings:

| Branch | 2.238.2 image | 2.303.1 image | Comparison |
|---|---|---|---|
| `GET MODELS:%c OK` | String at `0x080055fc`, reference near `0x0800542a` | String at `0x08005dd0`, reference near `0x08005a3e` | The compared handler windows contain 20 identical normalized Thumb instructions, including the model-byte load/compare/update shape. Strong evidence that this small selector branch was retained. |
| `M114` | Command near `0x08005806`; response references around `0x0800587e–0x0800591a` | Command near `0x08005eb0`; response references around `0x08005f26–0x08005fc2` | 120 of 121 normalized instructions match. Both builds read and clear the same one-shot event bit for `M114_DELATLIGHT_OVER`; the input pointer moves from `0x20000400` to `0x20000414`, consistent with the relocated command buffer. |
| `M410` | Token/string near `0x08005b5a–0x08005d88` | Token/string near `0x080060bc–0x08006354` | 104 of 105 normalized instructions match; the difference is a PC-relative literal load moved across a branch join. Control/store shape aligns, but global alias targets were not validated. |
| `M678` | Handler entry `0x08005c62` | Handler entry `0x080061c4` | Both parse the same seven fixed-stride slots (`+0x0b` through `+0x47`), optional `S` timer-array suffix at `+0x50`, and worker event flow. Parsed-value globals move by +8 bytes and the input-buffer base by +0x14. The newer build adds a `P2`-only pre-delay and two pairs of 3-byte calls using separate RAM buffers, with `0x14` delay arguments; their physical purpose and delay units remain unknown. This is a real protocol-path delta even though the common parameter layout is retained. |

The old image was extracted temporarily for this comparison and was not added to the repository. The later 2.303.1 image is the one already analyzed locally. This comparison makes the lineage more specific: the 2.238.2 download used for SKY/LITE/ONE PLUS/ONE PRO contains a multi-model TinaLinux `PrinterUI` build with CL60 and CL89 profiles and a CL60-style M678 template; the later CL-60 2.303.1 build retains those model labels/template and the byte-identical RK628 driver, while its host app, rootfs, kernel, and STM32 image changed. The selector branch and sampled M114/M410 code are closely related across revisions; M678 retains the common parser/event structure but adds a `P2` branch. Static comparison of `PrinterUI::lcdPrint` and its command builders shows the same layer call order and field construction across these two host builds (details below). Exact STM32 runtime equivalence, the added calls' physical purpose, and cross-model hardware behavior remain unproven. No independent raw STM32 UART trace from a second retail model was found.

### PrinterUI cross-version comparison

The 2.238.2 and 2.303.1 `PrinterUI` executables have different hashes, but their active CL60 layer path is strongly aligned: `lcdPrint` is 5,528 bytes in both and retains the same call order—compute `L`, select the initial or regular `M678` builder, submit the BGRA image, send the command over UART, then poll `WaitMotorStatus`/`M114`. The three `M678` builder functions also retain the same sizes and instruction shape, and both builds use the same `M678 Z%1 U%2 D%3 T%4 P%5 M%6 L%7 ` template. This is static code equivalence evidence, not a second-model runtime trace.

The host-side data sources are also mapped: `Z` comes from CXY offset `+0x18` (`PrintHeight`); `U` and `D` both come from `+0x1a` (`EleSpeed`); `T` comes from the layer/job field; initial-layer `P` is `InitExposure × 1000`, while regular-layer `P` is the CXY exposure value at `+0x04 × 1000`; `M` is `DelayLight` at `+0x20 × 1000`; and `L` comes from `GetCurLayoutArea`. This identifies host field provenance, not the physical meaning of the MCU operations. In particular, the CL60 XML defaults `PrintHeight=6` and `EleSpeed=1`, while the captured job sent `Z=5/10` and `U/D=2/3`, so those defaults are not the effective per-layer values from that print.

The serialized profile subtrees for CL60, CL89, CL89L, CL60RS, CL79, and CL70 match across the two XML files. CL60 uses serial type `E` and maps 1620×2560 to 540×2560; CL89 uses `A` and maps 3840×2400 to 1280×2400; CL89L uses `E`. These profile identifiers are separate from the MCU's `MODELS:` handshake byte.

## Comparison matrix

| Project or device family | Publicly established | Relation to this CL-60 port |
|---|---|---|
| HALOT-SKY / LITE / ONE PLUS / ONE PRO (2.238.2) | Four official support entries resolve to one identical archive and therefore one identical Linux and STM32 image set. Its multi-model `PrinterUI` contains CL60/CL89 profiles and the M678 template; key CL60 `lcdPrint` and builder functions match the later host build in size and control-flow shape. | Strongest cross-model software match found. The 2.303.1 STM32 retains the common M678 layout but adds a P2 sequence; no independent second-model raw trace confirms runtime behavior on SKY/LITE/ONE PLUS/ONE PRO. |
| HALOT-MAGE / MAGE S / MAGE PRO | These branches have separate firmware releases and different official board listings: the MAGE kit is marked `STM32F401RCT6`; the MAGE S exploded view lists `Mainboard Kit_V2.3.4_FQ6630_SSD202D`. Mage S tooling pins `V1_H2.228.1a2.228.1_C2.311.06_R2.230`; Creality lists Mage Pro `V1_H2.228.1a2.228.1_C2.309.04_R2.230`. The matching H2/R2 labels with different C2 strings suggest a related release line, not identical packages. | This is a clear hardware-family split within HALOT. No public Mage UART trace was found, so neither branch's MCU protocol should be projected onto CL-60. |
| HALOT-SKY hardware | An independent teardown reports Allwinner H6 + OpenWrt/Linux, STM32F103, and a Lontium LT6911C HDMI-to-MIPI bridge for the exposure screen. | Repeats the broad Linux-host + controller-MCU + separate image-bridge pattern seen on our CL-60, but uses a different SoC and bridge. No public UART capture located in this research confirms the CL-60 commands on SKY. |
| Creality-Control / Halot Box network path | The project's README says it derived WebSocket communication from a Wireshark capture while Halot software was connected. Its compatibility tracker lists Halot resin models on port 18188 as a distinct protocol family with testing still pending. | Useful prior art for PC/app-to-printer network traffic. It is a separate layer from PrinterUI-to-STM32 UART and does not disclose `M678` handler behavior. |
| UVtools / PrusaSlicer profiles | UVtools supports CXDLP and CXDLPV4; its repository contains profiles for CL-60, CL-89, CL-89L, CL-79, CL-70, and CL-103L. The first five use CXDLP; CL-103L uses CXDLPV4. Community-reported compatibility depends on CXDLP version and installed firmware. | Reusable today for sliced-job inspection/conversion. It is not a printer firmware, does not replace PrinterUI, and does not drive the CL-60 motion or panel directly. |
| Open Resin Alliance: Odyssey | Odyssey README targets Prusa SL1 job processing on Apollo boards and the Prometheus MSLA printer. It exposes configuration for a serial endpoint, framebuffer, pixel packing, G-code, UV/cure control, and synchronization replies. | A strong architectural reference for the host-side adapter we need. The HALOT serial dialect, fixed frame, RK628 display route, and `M678`/`M114` synchronization need a HALOT backend; the current README does not claim CL-60 support. |
| Open Resin Alliance: Orion | Orion is the UI frontend for Odyssey and is primarily documented for Linux SBC deployments, with Raspberry Pi and ARM64 build instructions. | Could inform a replacement operator UI after the stock graphics/touch ABI is understood. Installing Orion alone cannot control the HALOT's MCU or exposure panel. |
| Open Resin Alliance: LUMEN | LUMEN is a specified open job format with conformance vectors and a reference implementation. The project states that it is not printer-specific and requires firmware support. | A later input format for a port, once an adapter/backend reads LUMEN layers and schedules them through the recovered HALOT control/display contracts. It is not a drop-in `.cxdlp` replacement on stock firmware. |
| NanoDLP | NanoDLP documents a generic host/controller architecture using a framebuffer/LCD and a serial or compatible controller; its official controller board is based on configurable Marlin firmware. | Conceptually similar host/display/motion split, but no CL-60 compatibility is documented. Direct use would need an adapter or replacement controller and a proven display path. |
| Turbo Resin | The open firmware repository says it is based on reverse engineering the Anycubic Photon Mono 4K; its current build targets include Anycubic Mono 4K and Saturn. Its README lists Creality among possible future targets. | Useful reverse-engineering and embedded-firmware reference, not a HALOT port. The target board, LCD interface, boot path, and UV/motion hardware differ and need their own drivers. |
| Community HALOT firmware modifications | Mage S publishes a `ChituUpgrade.bin` with a U-Boot script that lists CIS, IPL, U-Boot, kernel, and UBI-volume writes; its toolkit source also includes a Linux/customer overlay. Mage Pro publishes a separate model-specific update mod. Neither has a published CL-60 port. | Useful Linux customization and update-research prior art. The Mage S release's exact stock-to-mod partition deltas and MCU equivalence remain unknown; do not infer that it changes only Linux. |

## Public protocol evidence and alternative firmware limits

The closest public HALOT-ONE reverse-engineering write-up is the 2022 Creation Factory article. It independently describes TinaLinux/OpenWrt, root access, `PrinterUI`, the Wi-Fi file-transfer service, and CL60 movement strings such as `G0 Z170 F1 D1 S1 H2`. This aligns with the host-side architecture and some command vocabulary in this repository. It is not a raw UART capture and does not document the `M678`/`M114` layer-completion exchange. Creality-Control adds a separate Wi-Fi/WebSocket observation from Halot Box, but its model tracker still marks individual resin variants for testing. Searches for `M678`, `M410_OK1`, `M114`, UART traces, and logic-analyzer captures across the public materials checked for SKY, ONE PLUS, MAGE, and LD-series machines did not locate an independent STM32 command table or wire trace. That is a bounded search result, not proof that no such material exists.

Alternative projects are useful at different layers, but none found here is a drop-in HALOT firmware. Odyssey is an engine aimed at Apollo/Prometheus; Orion is its UI; LUMEN is a job format; VoxelShift converts selected resin-printer formats to NanoDLP; NanoDLP expects a configurable controller protocol; Turbo Resin targets Anycubic Mono 4K/Saturn. The Mage S/Pro projects publish model-specific update artifacts for root, SSH, and file transfer, but do not document CL-60 support or a cross-model motion-controller port. Their partition-level changes remain unknown without unpacking and comparing those artifacts.

The Mage Pro project also documents reverse engineering of its embedded `Dwarf` slicer/firmware application and work on print-parameter acceptance. That is useful evidence that other HALOT models have active community modification work, but it is not a STM32 protocol trace and does not provide a CL60 port.

### What the Mage S rooted update actually contains

Static inspection of the published Mage S `ChituUpgrade.bin` shows a model-specific U-Boot updater script which lists and writes `cis`, partition-table, IPL, U-Boot, logo, kernel, rootfs, MI service, customer, and app-config payloads. The script includes `nand erase/write`, `ubi create/write`, and a UBI erase/recreate path. This establishes that the Mage S updater is capable of touching boot-chain and partition-layout components; it does **not** establish that the community modification changed the IPL/U-Boot bytes, nor that those payloads differ from the corresponding stock release. This is materially broader than a rootfs-only overlay and is not a CL-60 update route.

The Mage S toolkit source separately demonstrates a rootfs/customer overlay: its `apps.tar.gz` contains customer startup files and added `utelnetd`/`vsftpd` services and binaries, while `script.py` extracts UBI from a stock Mage S package, overlays the files, and repacks a `ChituUpgrade.bin`. The checked-in script pins C2.311.06, while the inspected public release asset is C2.311.7; therefore the current source overlay and tagged release image cannot be assumed to be the exact same build. The release package's complete partition payloads have not been compared byte-for-byte against the matching stock package, so we cannot conclude that its motion firmware or boot components are unchanged. No credentials are reproduced here.

| | HALOT-MAGE S rooted release | HALOT-ONE CL-60, local 2.303.1 package |
|---|---|---|
| Update container | Outer `.tar.gz` contains `ChituUpgrade.bin` (75,407,384 bytes), whose header identifies V2.311.7. | Outer `.tar.gz` contains `configUpdate.ini` and a `.swu`; the SWU is CPIO with `sw-description`, `recovery`, `uboot`, `kernel`, and `rootfs`. |
| Write path visible in package | U-Boot script lists CIS/partition-table, IPL, IPL_CUST, U-Boot, logo, kernel, and UBI volumes (`rootfs`, `miservice`, `customer`, `appconfigs`); it uses NAND erase/write and UBI create/write operations. | SWUpdate stages recovery and Allwinner `awuboot`, then writes kernel and rootfs to `/dev/by-name/boot` and `/dev/by-name/rootfs`. A separate startup service updates STM32 from `/etc/V1-01.bin` over `/dev/ttyS2`. |
| What remains unverified | Exact hashes and stock-versus-mod partition differences; whether an MCU image is embedded in a Linux partition. The visible updater script does not list a separate STM32 image. | The local package and installed rootfs match for the recorded components; the complete update path is documented in [firmware-update.md](firmware-update.md). |

This comparison establishes different update containers, boot chains, storage layouts, and MCU-update placement. The Mage S release script can rewrite boot-chain and UBI components, but does not prove that the community release changed their contents relative to stock. The current toolkit source pins C2.311.06, while the inspected release asset is C2.311.7, so source and release cannot be treated as one exact build. Its published `apps.tar.gz` establishes a Linux/customer overlay with added startup and network-service files; it does not prove the release left STM32 or boot components unchanged. The Mage S `ChituUpgrade.bin` and its NAND/UBI path provide no evidence of CL-60 compatibility. The transferable lesson is to audit every payload in the exact update artifact before calling a mod rootfs-only.

## Shared layers versus non-shared contracts

The ecosystem has at least four contracts, and evidence for one cannot stand in for another:

1. **Job container:** CXDLP/CXDLPV4, layer masks, thumbnails, and print metadata.
2. **Linux-to-controller control:** fixed UART frame and command/reply dialect on `/dev/ttyS2` for this CL-60.
3. **Image presentation:** the separate H616 HDMI → RK628 → MIPI DSI path and the panel's pixel/channel mapping.
4. **Electrical board interface:** connectors, signal levels, motor driver, UV outputs, sensors, and boot/reset wiring.

Public CXDLP support establishes layer 1 only. Our live trace and static disassembly establish much of layer 2 for one firmware. The H616/RK628 trace establishes a large part of layer 3, but physical pixel mapping remains open. Layer 4 still needs board-level evidence. A model can share CXDLP while differing in every other layer.

## What to investigate next

Next, compare the 2.238.2 and 2.303.1 command builders and STM32 handlers at the function level, then map the older build's model-selection values onto the XML profiles. For a sibling-machine claim, obtain a passive UART trace from a known model/profile or a distinct officially published model-specific binary. Any binary match should be reported by cryptographic hash; similar filenames or shared command names are insufficient.

Do not send motion, reset, or UV commands to the CL-60 just to check whether another model's protocol is accepted.

## Sources

- [Creality HALOT-ONE downloads](https://www.creality.com/download/creality-halot-one-resin-3d-printer)
- [Creality HALOT-MAGE firmware support page](https://www.creality.com/support/halot-mage-3d-printer)
- [Creality HALOT-ONE PLUS downloads](https://www.creality.com/download/halot-one-plus-3d-printer)
- [Creality HALOT family firmware catalog](https://www.crealitycloud.com/tr/downloads/firmware/halot-series)
- [Creality HALOT-SKY firmware page](https://www.creality.com/download/halot-sky-3d-printer)
- [Creality HALOT-LITE firmware page](https://www.creality.com/download/creality-halot-lite-resin-3d-printer)
- [Creality HALOT-ONE PRO firmware page](https://www.creality.com/download/halot-one-pro-3d-printer)
- [Shared 2.238.2 HALOT firmware archive](https://file2-cdn.creality.com/file/63c45268ee001da26529f5f3629f7834/V1_H2.238.2a2.238.2_C2.238.2_R2.238.2.tar.gz)
- [Independent HALOT-SKY hardware teardown](https://3dtoday.ru/blogs/dagov/fotopolimernyi-monstr-ot-creality-halot-sky)
- [UVtools](https://github.com/sn4k3/UVtools)
- [UVtools CL-60 PrusaSlicer profile](https://github.com/sn4k3/UVtools/blob/master/PrusaSlicer/printer/Creality%20Halot%20One%20CL-60.ini)
- [UVtools model profiles](https://github.com/sn4k3/UVtools/tree/master/PrusaSlicer/printer)
- [CHITUBOX format compatibility list](https://docs.chitubox.com/en-US/chitubox/latest/introduction)
- [UVtools CXDLP implementation](https://github.com/sn4k3/UVtools/blob/master/UVtools.Core/FileFormats/CrealityCXDLPFile.cs)
- [UVtools CXDLPV4 implementation](https://github.com/sn4k3/UVtools/blob/master/UVtools.Core/FileFormats/CrealityCXDLPv4File.cs)
- [UVtools discussion of CXDLP settings](https://github.com/sn4k3/UVtools/discussions/624)
- [Open Resin Alliance Odyssey](https://github.com/Open-Resin-Alliance/Odyssey)
- [Open Resin Alliance Orion](https://github.com/Open-Resin-Alliance/Orion)
- [Open Resin Alliance LUMEN format](https://github.com/Open-Resin-Alliance/LumenFormat)
- [NanoDLP controller documentation](https://docs.nanodlp.com/guide/controller-board/)
- [Turbo Resin open firmware](https://github.com/nviennot/turbo-resin)
- [HALOT-MAGE S Toolkit](https://github.com/rogersstuart/Halot-Mage-S-Toolkit)
- [HALOT-MAGE S Toolkit overlay archive](https://github.com/rogersstuart/Halot-Mage-S-Toolkit/blob/main/apps.tar.gz)
- [HALOT-MAGE S Toolkit repack script](https://github.com/rogersstuart/Halot-Mage-S-Toolkit/blob/main/script.py)
- [HALOT-MAGE S Toolkit overlay extraction script](https://github.com/rogersstuart/Halot-Mage-S-Toolkit/blob/main/extract_apps.py)
- [HALOT-MAGE S rooted firmware release](https://github.com/weashadow/UltraFirmwareToolkit/releases/tag/Creality-Halot-Mage-S)
- [UltraFirmwareToolkit UBI tooling](https://github.com/weashadow/UltraFirmwareToolkit)
- [HALOT-MAGE PRO mods](https://github.com/xyzzyi/Halot-mage-PRO-MSLA-mods)
- [HALOT-MAGE PRO mod release notes](https://github.com/xyzzyi/Halot-mage-PRO-MSLA-mods/releases)
- [Creality HALOT-MAGE PRO stock firmware](https://www.creality.com/download/halot-mage-pro-3d-printer)
- [Open Resin Alliance VoxelShift](https://github.com/Open-Resin-Alliance/VoxelShift)
- [Independent 2022 HALOT-ONE root and network notes](https://www.creationfactory.co/2022/01/rooting-creality-halot-one-resin-3d.html)
- [Creality-Control WebSocket integration](https://github.com/SiloCityLabs/Creality-Control)
- [Creality-Control model compatibility tracker](https://github.com/SiloCityLabs/Creality-Control/issues/1)
- [Official Creality HALOT-MAGE mainboard with STM32F401RCT6](https://mvip.creality.com/en/goods/goodsDetail/1984)
- [Official Creality HALOT-MAGE S board listing](https://vip.creality.com/en/goods-detail/2201)
- [Official Creality HALOT-MAGE S exploded view](https://vip.creality.com/en/exploded-view-detail/168)
- [Reseller listing with HALOT-MAGE S V2.3.4 and FQ6630/SSD202D board identifiers](https://crealitybrasil.com.br/products/placa-mae-para-impressora-3d-halot-mage-s-creality-v2-3-4-fq6630-ssd202d)
