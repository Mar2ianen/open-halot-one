# Open HALOT ONE

Hardware and firmware research notes for the Creality HALOT-ONE (CL-60). This is a living map built from a read-only inspection of one running unit, firmware artifacts, and published product documentation.

## Current observations

- The unit reports model `CL60` and runs Allwinner TinaLinux on an Allwinner H616 (`sun50iw9`) with four Cortex-A53 cores.
- The captured OS is TinaLinux `Neptune 272`, target `h616-p2/generic v2.1`, with Linux `4.9.170`.
- It has a 5-inch color touch interface and a separate 5.96-inch monochrome resin exposure LCD. The manual labels separate `RGB screen` and `LCD resin panel` connections.
- Creality lists the HALOT-ONE replacement mainboard as `Kit_2.0_32_A4988_STM32` (part `4002010045`); the exact PCB revision in the inspected unit still needs a photo.
- The operator screen is configured by the H616 display engine as `800x480@59 Hz` on its RGB24 pin group; touch uses `cxsw_ctp` on I²C bus 3, address `0x38`.
- While running, PrinterUI held `/dev/ttyS2`, `/dev/fb0`, `/dev/disp`, and touch input open. The firmware updater also selects `/dev/ttyS2` for the STM32 control path. PrinterUI uses 115200 8N1 without flow control; the cable, voltage, and MCU pin mapping still need physical tracing.
- The second display path exposes `cxsw,dlp1438` at I²C0 `0x1b` with `power`, `spi_ready`, and `print_status` properties, plus an active Rockchip RK628 bridge on I²C2 `0x50`. Which component drives the exposure LCD and how the FPC is wired remain unresolved.

Evidence labels in the docs distinguish direct device observations, published specifications, and inferences. See [the hardware map](docs/hardware-map.md), [software map](docs/software-map.md), [UART and STM32 protocol map](docs/protocols.md), [firmware/update and boot analysis](docs/firmware-update.md), [PrinterUI analysis](docs/printerui-analysis.md), and [snapshot notes](docs/system-snapshot.md).

## Data handling

The public repository contains sanitized documentation only. The full per-device eMMC image, boot-area images, original `PrinterUI` executable, and Ghidra project are stored locally in the owner's private output archive because they contain device-specific data or vendor binaries. Serial numbers, MAC addresses, Wi-Fi credentials, keys, and user print files are not published here.

## Sources

- [Creality HALOT-ONE downloads and firmware](https://www.creality.com/download/creality-halot-one-resin-3d-printer)
- [Creality Cloud HALOT-ONE firmware listing](https://www.crealitycloud.com/ru/downloads/firmware/halot-series/halot-one)
- [Creality HALOT-ONE mainboard kit](https://www.crealitycloud.com/product/spare-parts/halot-one-mainboard-kit-62ee0546a99b803c8f3f4513)
- [Creality HALOT-ONE user manual (CL-60-SM-003)](https://www.bhphotovideo.com/lit_files/839713.pdf)
- [Rooting the Creality HALOT-ONE](https://www.creationfactory.co/2022/01/rooting-creality-halot-one-resin-3d.html)
