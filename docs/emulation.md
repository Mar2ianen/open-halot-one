# Emulator and launch-time tracing experiments

## Linux root filesystem and PrinterUI

The official update archive `V1_H2.303.1a2.303.1_C2.302.4_R2.302.1.tar.gz` contains an SWU with a 111,935,488-byte SquashFS root filesystem. Its executables, including `PrinterUI`, are 32-bit ARM EABI5 hard-float (`armhf`), not AArch64. This is the userspace running on Tina Linux; the printer's H616 board and vendor kernel remain separate parts of the system.

The extracted rootfs and PrinterUI were run under QEMU ARM user-mode in a disposable, network-isolated container. The application loaded its Qt EGLFS/Mali platform integration, attempted `/dev/mali0`, then aborted because the Mali kernel driver/device node is absent. The trace did not reach a usable display or UART session. This confirms the userspace architecture and some startup choices, but it does not emulate the H616, its display engine, ION, RK628, or the printer peripherals.

## STM32 control image

The MCU image was tried on two QEMU Cortex-M3 boards:

| QEMU machine | Result |
|---|---|
| `stm32vldiscovery` | The model's SRAM is too small: the image's initial stack pointer is `0x20004460`, and startup writes near `0x20004440` were outside the emulated RAM. |
| `netduino2` | RAM is sufficient to progress through early initialization, but the board does not model the peripheral map used by this image. QEMU reports invalid MMIO accesses in the regions around `0x40021000`, `0x40010800`, and `0x40020000`. |

Those addresses match the STM32F1-style RCC, GPIOA, and DMA1 regions. This is strong evidence for an STM32F1-compatible peripheral map, but it does not identify the exact MCU or board revision. QEMU's available board models do not provide the needed combination of SRAM size and matching STM32F1 peripherals, so their later register values and execution state are not meaningful evidence about the printer firmware. No protocol conclusions were inferred from these failed board runs.

## Launch-time `strace` on the printer

Attaching `strace` to the already-running UI was denied by the device's ptrace policy. Starting the UI as a child of `strace -f` worked. For the experiment, the existing `S99cxpm-ui` service entry was launched manually under `strace`; no persistent init file was edited, and the separate `S21stm32_update` boot service was not run. This captured one UART startup exchange documented in [the protocol map](protocols.md).

The broad syscall trace perturbed this UI build: startup logged a heap-corruption error. The tracer and tracee were stopped, the ordinary `S99cxpm-ui` service was restarted, and the live UI was verified running without a tracer. The trace did not issue print, UV, or motor commands. A narrower syscall filter may reduce overhead, but this first run shows the capture should be treated as a short, timing-perturbed sample rather than a stable long-duration trace.

## What would make emulation useful

- Identify the STM32 marking from an external board photo or later physical inspection; then select or build a matching MCU model with the right flash, SRAM, RCC, GPIO, DMA, timers, SPI, and UART.
- For the Linux UI, provide a matching H616 kernel and the vendor `/dev/mali0`, `/dev/disp`, and ION interfaces, or build explicit test doubles for them and a fake UART endpoint. QEMU user-mode alone cannot reproduce those kernel drivers.
- Keep the present emulation artifacts and raw syscall traces private. They include vendor firmware or machine-specific runtime data and are not needed in the public documentation repository.

The experiments were offline or read-only with respect to the printer. No update, bootloader, partition, or MCU write was performed.
