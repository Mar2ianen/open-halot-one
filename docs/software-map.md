# Software map

## Observed operating system

- SoC/target: Allwinner H616 (`sun50iw9`, device-tree compatible `allwinner,h616`). The processor exposes four ARM Cortex-A53 cores.
- OS release file: TinaLinux `Neptune 272`, build timestamp `2023-09-04`, target `h616-p2/generic v2.1`, description `3.5.1`.
- Kernel: Linux `4.9.170`, build `#700`, compiled 2023-09-04.
- Bootloader string in the kernel command line: U-Boot `2018.05`.
- Init: OpenWrt-style `procd`; root filesystem is read-only SquashFS with an ext4 overlay.
- UI: Qt 5 application at `/usr/bin/PrinterUI/PrinterUI`, with external Qt/QML resource bundles.

## Storage layout observed from `/proc/partitions` and mounts

The user area is eMMC `/dev/mmcblk0`, 7,636,800 KiB. The start and size values below are 512-byte sectors read from sysfs. The kernel command line maps ten GPT partitions:

| Partition | Kernel label | Start | Size | Observed use / mount |
|---|---|---:|---:|---|
| `p1` | bootloader | 73,728 | 65,536 | FAT16 volume with `hbootlogo.bmp`, `vbootlogo.bmp`, `bootlogo.bmp`, and `magic.bin`; the GPT label does not mean this partition contains executable U-Boot |
| `p2` | env | 139,264 | 32,768 | boot environment |
| `p3` | env-redund | 172,032 | 32,768 | redundant boot environment |
| `p4` | recovery | 204,800 | 65,536 | recovery image |
| `p5` | boot | 270,336 | 65,536 | boot image |
| `p6` | rootfs | 335,872 | 317,440 | SquashFS mounted read-only at `/rom` (106.8 MiB) |
| `p7` | rootfs_data | 653,312 | 138,240 | ext4 overlay at `/overlay` (61.4 MiB) |
| `p8` | misc | 791,552 | 32,768 | misc region |
| `p9` | private | 824,320 | 32,768 | VFAT mounted at `/device` (16 MiB) |
| `p10` | UDISK | 857,088 | 14,416,479 | ext4 mounted at `/mnt/UDISK` (6.6 GiB) |

The separate 4 MiB eMMC hardware areas `boot0` and `boot1` were captured and are entirely zero-filled; both are read-only while Linux runs. Comparing the vendor TOC1 member against the full user-area snapshot found an exact package copy at byte offset `0x01004000` in the reserved area before `p1`. Static reversal shows that SWUpdate's `awuboot` path clears 1 MiB at `0x012a6000`, then writes the package at sector `0x8020` (`0x01004000`); the first region's role is unknown. The package's embedded U-Boot version matches the running `2018.05-g14fbabb0`. The first-stage BOOT0/SPL strings also occur in the user-area prefix, but BootROM selection rules remain unknown; see [firmware and boot path](firmware-update.md). RPMB was not read.

## Live display pipeline

- The operator touchscreen is the Allwinner `lcd0` framebuffer at `/dev/fb0`: `U:800x480p-59`, 32 bits per pixel, virtual size `800x960`. The touch controller remains the separate I²C3 `0x38` input device.
- The active exposure stream appears separately at the H616 HDMI output. Kernel logs show the RK628 HDMI receiver at I²C2 `0x50` detecting 540×2560 input at 74.25 MHz and configuring 540×2560 output at 80.035 MHz.
- RK628 successfully initializes MIPI DSI1 at four lanes, 840 Mb/s per lane; `/sys/devices/virtual/rk628_class/rk628/attr/dsi_err` reads `0`. The kernel creates `/dev/rk628` (character device 242:0). `lcd_timing`, `lane_rate`, `dsi_enable`, and `hdmi_out_enable` sysfs nodes exist but return `EIO` when read in this firmware; they were not written.
- The 540-pixel active width matches PrinterUI's 3:1 compression of the 1620-pixel layer width. That ties the image pipeline to the RK628/DSI path with high confidence. The exact RGB channel packing into monochrome panel columns and the physical DSI FPC route are not yet known.
- A separate I²C0 `0x1b` device-tree node advertises `cxsw,dlp1438`, but its probe reports `device not the CD60` and exits with `-22`; no driver binds. Do not treat that node as the working CL60 exposure path.

## Runtime services observed

The process list included `procd`, `ubusd`, `netifd`, `wpa_supplicant`, `wifi_daemon`, `sshd`, `adbd -D`, `ntpd`, the Qt PrinterUI, and Creality's WebRTC camera helper. The PrinterUI listener on TCP port `18188` was bound to a specific local address; the address itself is omitted from public docs. This does not prove internet reachability. Input devices were `sunxi-keyboard` (`event0`), `sunxi-ir` (`event1`), and `cxsw_ctp` touch (`event2`). A WebRTC helper was running, but no `/dev/video*` node was present in this inspection, so camera capture hardware is not confirmed.

## PrinterUI binary clone

The live executable was copied through the printer's ADB sync service. Local facts:

- SHA-256: `a0a0b919bf2a7cc181c120be5e0983624511e25e7eb24406c65e0a6b20d5e8c1`
- Size: 4,561,896 bytes
- Format: little-endian ELF32, ARM EABI5, hard-float, dynamically linked
- Interpreter: `/lib/ld-linux-armhf.so.3`
- It depends on Qt 5, OpenCV 3.3, FFmpeg 3.x, `libcxdlp.so`, `libcxWebsocket.so`, `libnettrans.so`, and `libwifimg.so` among other libraries.
- Embedded method names include `SerialPortPrintFile`, `parseOnePictureFromCxdlp`, `parseOnePictureFromCxline`, `lcdPrint`, `waitRecvMsgFromSerial`, `getMotorMoveUpCommand`, and `getMotorMoveDownCommand`.
- The binary contains a `/dev/ttyUSB0` string. The live kernel inventory showed `ttyS0`/`ttyS1`/`ttyS2` and no `ttyUSB*`; that string by itself does not identify the connected STM32 endpoint.
- Runtime check adds a stronger fact: the live PrinterUI process held `/dev/ttyS2` open. The device tree maps it to the enabled Allwinner UART2 controller at `0x05000800`; `ttyS0` remains the Linux console. This makes UART2 the leading control-board link candidate, but does not prove which PCB connector or MCU pin it reaches.
- Ghidra pseudocode for `MainView::InitSerialPort` constructs `CXSerial` with baud argument `0x1c200` (115,200). The device path is assembled from runtime strings/configuration, while `Controller::checkDev_ttyUSB0` has an explicit `ttyUSB0` check. In the inspected running state the open path resolves to `/dev/ttyS2`.
- PrinterUI also held `/dev/fb0`, `/dev/disp`, `/dev/ion`, `/dev/mali0`, and all three input event nodes open. It had a TCP listener on port `18188` bound to a specific local address; the address itself is omitted from public docs. This records a local service endpoint, not proof of internet reachability.
- The build strings include the vendor path `cxpm2-2.303.1`; this is a candidate application build version, not yet independently verified against a UI version screen or package metadata.
- The serial link is configured as 115,200 baud, 8 data bits, no parity, one stop bit, no flow control. The live updater and PrinterUI both select `/dev/ttyS2` for this product. The STM32 package and GPIO reset/BOOT0 sequence confirm that the UART is used for the controller path; exact board pins and signal voltage remain unverified.
- The `SendMsgToSerial` path sends a command in a 100-byte ASCII frame: command text followed by spaces, four `0x55` bytes at offsets 96–99, then LF. The code computes a 16-bit sum of bytes 0–95 but does not place it in the transmitted buffer. Replies are read as LF-terminated lines, at most 100 bytes; the parser splits response type and payload on `_`. A separate `Meng` path writes its string directly and also reads line replies. These are static findings; no UART traffic was captured.

The executable clone, focused Ghidra project, and pseudocode exports are local artifacts. This repository records the analysis results without redistributing the vendor executable or bulk decompiled source. See [the PrinterUI analysis](printerui-analysis.md) for the call flow and function addresses, [the protocol map](protocols.md) for the UART framing and STM32 command catalog, and [the firmware/update analysis](firmware-update.md) for the vendor update chain.

## Analysis method

Ghidra 12.1.4 was downloaded from the [official NSA GitHub project](https://github.com/NationalSecurityAgency/ghidra), and its SHA-256 was verified against the release asset digest before importing the ARM binary. The full binary auto-analysis completed; a focused script exported pseudocode for 723 functions cross-referenced from display, file-format, serial, motor, network, and update strings. Function addresses and pseudocode are retained in the private local archive; high-level findings are documented in [the analysis note](printerui-analysis.md).
