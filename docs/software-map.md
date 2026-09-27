# Software map

## Observed operating system

- SoC/target: Allwinner H616 (`sun50iw9`, device-tree compatible `allwinner,h616`). The processor exposes four ARM Cortex-A53 cores.
- OS release file: TinaLinux `Neptune 272`, build timestamp `2023-09-04`, target `h616-p2/generic v2.1`, description `3.5.1`.
- Kernel: Linux `4.9.170`, build `#700`, compiled 2023-09-04.
- Bootloader string in the kernel command line: U-Boot `2018.05`.
- Init: OpenWrt-style `procd`; root filesystem is read-only SquashFS with an ext4 overlay.
- UI: Qt 5 application at `/usr/bin/PrinterUI/PrinterUI`, with external Qt/QML resource bundles.

## Storage layout observed from `/proc/partitions` and mounts

The user area is eMMC `/dev/mmcblk0`, 7,636,800 KiB. The kernel command line maps ten GPT partitions:

| Partition | Kernel label | Observed use / mount |
|---|---|---|
| `p1` | bootloader | bootloader region |
| `p2` | env | boot environment |
| `p3` | env-redund | redundant boot environment |
| `p4` | recovery | recovery image |
| `p5` | boot | boot image |
| `p6` | rootfs | SquashFS mounted read-only at `/rom` |
| `p7` | rootfs_data | ext4 overlay at `/overlay` |
| `p8` | misc | misc region |
| `p9` | private | VFAT mounted at `/device` |
| `p10` | UDISK | ext4 mounted at `/mnt/UDISK` |

The eMMC device also exposes separate `boot0` and `boot1` hardware areas. Their captures and hashes are recorded in the local snapshot manifest. RPMB was not read.

## Runtime services observed

The process list included `procd`, `ubusd`, `netifd`, `wpa_supplicant`, `wifi_daemon`, `sshd`, `adbd -D`, `ntpd`, the Qt PrinterUI, and Creality's WebRTC camera helper. A process name alone does not prove the service is reachable from another host; network listeners and firewall policy are being checked separately.

## PrinterUI binary clone

The live executable was copied through the printer's ADB sync service. Local facts:

- SHA-256: `a0a0b919bf2a7cc181c120be5e0983624511e25e7eb24406c65e0a6b20d5e8c1`
- Size: 4,561,896 bytes
- Format: little-endian ELF32, ARM EABI5, hard-float, dynamically linked
- Interpreter: `/lib/ld-linux-armhf.so.3`
- It depends on Qt 5, OpenCV 3.3, FFmpeg 3.x, `libcxdlp.so`, `libcxWebsocket.so`, `libnettrans.so`, and `libwifimg.so` among other libraries.
- Embedded method names include `SerialPortPrintFile`, `parseOnePictureFromCxdlp`, `parseOnePictureFromCxline`, `lcdPrint`, `waitRecvMsgFromSerial`, `getMotorMoveUpCommand`, and `getMotorMoveDownCommand`.
- The binary contains a `/dev/ttyUSB0` string. The live kernel inventory showed `ttyS0`/`ttyS1`/`ttyS2` and no `ttyUSB*`; that string by itself does not identify the connected STM32 endpoint.
- The build strings include the vendor path `cxpm2-2.303.1`; this is a candidate application build version, not yet independently verified against a UI version screen or package metadata.

The executable clone and focused Ghidra decompilation are local artifacts. This repository records the analysis results without redistributing the vendor executable or bulk decompiled source.

## Analysis method

Ghidra 12.1.4 was downloaded from the official NSA GitHub release and its SHA-256 verified against the release asset digest before importing the ARM binary. Focused decompilation targets functions cross-referenced from display, file-format, serial, motor, network, and update strings. Function addresses and pseudocode are retained in the private local archive; results will be summarized here as they are confirmed.
