# Open HALOT ONE

Hardware and firmware research notes for the Creality HALOT-ONE (CL-60). This is a living map built from a read-only inspection of one running unit, firmware artifacts, and published product documentation.

## Current observations

- The unit reports model `CL60` and runs Allwinner TinaLinux on an Allwinner H616 (`sun50iw9`) with four Cortex-A53 cores.
- The captured OS is TinaLinux `Neptune 272`, target `h616-p2/generic v2.1`, with Linux `4.9.170`.
- It has a 5-inch color touch interface and a separate 5.96-inch monochrome resin exposure LCD. The manual labels separate `RGB screen` and `LCD resin panel` connections.
- Creality lists the HALOT-ONE replacement mainboard as `Kit_2.0_32_A4988_STM32` (part `4002010045`); the exact PCB revision in the inspected unit still needs a photo.
- The operator screen is configured by the H616 display engine as `800x480@59 Hz` on its RGB24 pin group; touch uses `cxsw_ctp` on I²C bus 3, address `0x38`.
- While running, PrinterUI held `/dev/ttyS2`, `/dev/fb0`, `/dev/disp`, and touch input open. Linux `/dev/ttyS2` is H616 UART2; static STM32 analysis ties the command parser to MCU USART1 RX. The likely host-to-controller path is H616 UART2 to STM32 USART1. PrinterUI uses 115200 8N1 without flow control; the cable, voltage, and exact pin mapping still need physical tracing.
- The exposure-image path is traced in live kernel logs from H616 HDMI at 540×2560 through the RK628 at I²C2 `0x50` to MIPI DSI1, four lanes at 840 Mb/s each. Static PrinterUI analysis shows how each group of three source samples is packed into the active BGRA output pixel. The remaining physical panel-column mapping and FPC trace are documented separately.
- The vendor TOC1 U-Boot package exactly matches bytes at eMMC user-area offset `0x01004000`; hardware `boot0`/`boot1` captures are zero-filled. Static reversal of the installed `awuboot` handler shows it clears 1 MiB at `0x012a6000`, then writes the package at `0x01004000`. The normal path reads the `boot` GPT partition and calls `bootm`; a tested rollback route remains unknown.

Evidence labels in the docs distinguish direct device observations, published specifications, and inferences. See [the hardware map](docs/hardware-map.md), [software map](docs/software-map.md), [UART and STM32 protocol map](docs/protocols.md), [WebSocket control protocol](docs/network-control-protocol.md), [exposure display data path](docs/display-pipeline.md), [reverse-engineering gap map](docs/reverse-engineering-gaps.md), [emulator and tracing experiments](docs/emulation.md), [firmware/update and boot analysis](docs/firmware-update.md), [ORA port plan](docs/ora-port-plan.md), [related platforms and alternative firmware](docs/related-platforms.md), [PrinterUI analysis](docs/printerui-analysis.md), and [snapshot notes](docs/system-snapshot.md).

The sanitized UART analyzer can decode syscall traces without including device captures in this repository: `python3 tools/decode_strace_uart.py capture.strace --fd 28 --cycles`.

## Data handling

The public repository contains sanitized documentation only. The full per-device eMMC image, boot-area images, original `PrinterUI` executable, and Ghidra project are stored locally in the owner's private output archive because they contain device-specific data or vendor binaries. Serial numbers, MAC addresses, Wi-Fi credentials, keys, and user print files are not published here.

## Sources

- [Creality HALOT-ONE downloads and firmware](https://www.creality.com/download/creality-halot-one-resin-3d-printer)
- [Creality Cloud HALOT-ONE firmware listing](https://www.crealitycloud.com/ru/downloads/firmware/halot-series/halot-one)
- [Creality HALOT-ONE mainboard kit](https://www.crealitycloud.com/product/spare-parts/halot-one-mainboard-kit-62ee0546a99b803c8f3f4513)
- [Creality HALOT-ONE user manual (CL-60-SM-003)](https://www.bhphotovideo.com/lit_files/839713.pdf)
- [Rooting the Creality HALOT-ONE](https://www.creationfactory.co/2022/01/rooting-creality-halot-one-resin-3d.html)
