# Emulator and launch-time tracing experiments

## Linux root filesystem and PrinterUI

The official update archive `V1_H2.303.1a2.303.1_C2.302.4_R2.302.1.tar.gz` contains an SWU with a 111,935,488-byte SquashFS root filesystem. Its executables, including `PrinterUI`, are 32-bit ARM EABI5 hard-float (`armhf`), not AArch64. This is the userspace running on Tina Linux; the printer's H616 board and vendor kernel remain separate parts of the system.

The extracted rootfs and PrinterUI were run under QEMU ARM user-mode in a disposable, network-isolated container. The application loaded its Qt EGLFS/Mali platform integration, attempted `/dev/mali0`, then aborted because the Mali kernel driver/device node is absent. This Qt build has no `libqoffscreen.so`; selecting `QT_QPA_PLATFORM=offscreen` therefore also aborts. `QT_QPA_PLATFORM=linuxfb` gets past Mali initialization but then lacks `/dev/fb0`; the experiment also ran outside the target root mount, so its `/mnt/UDISK/cxpmRunning.log` failure is not a target-system behavior. None of these launches reached a usable UART session. These results explain why host-side UI execution is not needed for the MCU protocol reverse: the controller binary can be disassembled directly, and the protocol framing is now recovered from its USART1 receive path. QEMU user-mode still does not emulate the H616 display engine, ION, RK628, or printer peripherals.

## STM32 control image

The MCU image was tried on two QEMU Cortex-M3 boards:

| QEMU machine | Result |
|---|---|
| `stm32vldiscovery` | The model's SRAM is too small: the image's initial stack pointer is `0x20004460`, and startup writes near `0x20004440` were outside the emulated RAM. |
| `netduino2` | RAM is sufficient to progress through early initialization, but the board does not model the peripheral map used by this image. QEMU reports invalid MMIO accesses in the regions around `0x40021000`, `0x40010800`, and `0x40020000`. |

Those addresses match the STM32F1-style RCC, GPIOA, and DMA1 regions. This is strong evidence for an STM32F1-compatible peripheral map, but it does not identify the exact MCU or board revision. QEMU's available board models do not provide the needed combination of SRAM size and matching STM32F1 peripherals, so their later register values and execution state are not meaningful evidence about the printer firmware. No protocol conclusions were inferred from these failed board runs.

### Renode follow-up

Renode `1.16.1.16973` provides an [STM32F103 Cortex-M3 platform](https://github.com/renode/renode/blob/master/platforms/cpus/stm32f103.repl) that is a closer starting point than either QEMU board. The Creality image was loaded at `0x08000000` with its vector-table offset set to that address, initial SP `0x20004460`, and reset PC `0x0800019c`. The stock platform description has USART/GPIO models but no behavioral RCC or DMA model in this Renode build. A private RCC stub was therefore used to report HSI/HSE/PLL ready and reflect the requested clock source; DMA1 and Flash control were temporarily represented by memory-backed register windows. These stubs are experiment fixtures, not models of the actual chip. Renode documents [Python peripherals](https://renode.readthedocs.io/en/latest/basic/using-python.html) as one way to model or mock missing blocks.

With those fixtures the image clears its RCC startup waits and configures serial DMA before continuing into application code. The observed configuration is consistent with USART1 RX on DMA1 channel 5 (200-byte buffer at `0x20000578`), USART2 RX on channel 6 (200-byte buffer at `0x200007d0`), and USART2 TX on channel 7 (data register `0x40004404`, buffer at `0x20000640`). USART2's CR3 is written with `0xc0` (DMAT and DMAR). This is register-configuration evidence from CPU execution, not a captured UART byte stream. The memory-backed DMA registers do not move bytes, raise transfer-complete flags, or model request timing, so this run cannot validate the protocol or show that these channels complete a transfer.

A five-second virtual-time run progressed beyond this setup; a sampled PC landed in a bytewise string-comparison routine. Because DMA, Flash wait states, and peripheral timing are still incomplete, that PC sample is not enough to identify the main-loop state. No command replies or image payloads have been generated in Renode.

### Static UART interrupt and frame-path disassembly

Disassembly of the shipped `V1-01.bin` resolves the command receive path without relying on GPU or MCU emulation. The vector table points USART1, USART2, and USART3 to handlers at `0x08003078`, `0x080031a0`, and `0x0800321c`; DMA1 channel7 has a custom handler at `0x08001252`. The USART handlers use selector `0x424` with a helper at `0x080033f8` that checks the USART `CR1.IDLEIE` enable and `SR.IDLE` flag. USART1's IDLE path rearms DMA1 channel5 and copies `200 - CNDTR` bytes from `0x20000578` into the command mailbox at `0x200004b0`.

The consumer at `0x08006ddc` checks `mailbox[99] == 0x55` before calling the dispatcher at `0x08005510`; the dispatcher tokenizes the command at `0x080041f0`. This matches PrinterUI's 100-byte body ending in four `0x55` bytes, followed by LF. Static code therefore establishes the software-side frame marker and dispatch path. It still does not provide a live MCU UART transcript, test DMA timing, or identify the physical board pins. See [the protocol map](protocols.md) for the complete receive sequence and limits.

## Launch-time `strace` on the printer

Attaching `strace` to the already-running UI was denied by the device's ptrace policy. Starting the UI as a child of `strace -f` worked. For the experiment, the existing `S99cxpm-ui` service entry was launched manually under `strace`; no persistent init file was edited, and the separate `S21stm32_update` boot service was not run. This captured one UART startup exchange documented in [the protocol map](protocols.md).

The broad syscall trace perturbed this UI build: startup logged a heap-corruption error. The tracer and tracee were stopped, the ordinary `S99cxpm-ui` service was restarted, and the live UI was verified running without a tracer. The trace did not issue print, UV, or motor commands. A narrower syscall filter may reduce overhead, but this first run shows the capture should be treated as a short, timing-perturbed sample rather than a stable long-duration trace.

## What would make emulation useful

- Identify the STM32 marking from an external board photo or later physical inspection; then complete the Renode model for its RCC, Flash, DMA request routing, timers, SPI, and UART. The documented Renode STM32F103 platform is a useful base, and Renode's Python peripheral mechanism can mock or implement missing register blocks, but each mock must reproduce the side effects that the firmware polls before using the result.
- For a faithful Linux UI run, provide a matching H616 kernel and the vendor `/dev/mali0`, `/dev/disp`, and ION interfaces, or build explicit test doubles for them and a fake UART endpoint. QEMU user-mode alone cannot reproduce those kernel drivers.
- Keep the present emulation artifacts and raw syscall traces private. They include vendor firmware or machine-specific runtime data and are not needed in the public documentation repository.

### What “emulate Mali” can mean here

The live driver reports `Mali-G31 1 core r0p0 0x7093`; the loaded `mali_kbase` module reports `r20p0-01rel0 (UK version 11.17)`. The captured device tree uses the generic compatible string `arm,mali-midgard`, so the driver's live `gpuinfo` is the more specific model evidence. PrinterUI opens `/dev/mali0`, while the operator-screen scanout is separately exposed as H616 `lcd0`/`fb0`; the exact Qt render-target-to-scanout path has not been traced.

| Goal | Available approach | What it would and would not reproduce |
|---|---|---|
| Run graphics API calls without the printer GPU | QEMU `virtio-gpu` with VirGL, or a Mesa/SwiftShader software renderer | Can provide a virtual OpenGL/GLES path for a guest or adapted application. It does not implement the H616 kbase ABI, `/dev/mali0`, Sunxi ION, `/dev/disp`, or RK628 display route. |
| Exercise a real Mali-style kernel-driver integration virtually | Arm Fast Models Graphics Register Model (GRM) | Arm documents a Mali-G71 register model that invokes the host GPU for rendering and supports integration testing with the Mali driver stack. It is not a Mali-G31 model, so it is not an exact match for this printer. |
| Run this unmodified PrinterUI against its expected device interfaces | Use the printer's H616/G31 stack, or build compatible test doubles and replace/redirect the display backend | The stock binary depends on vendor kernel interfaces and the H616 display path; a generic GPU API emulator alone is insufficient. |

Mesa Panfrost supports Mali-G31 on real hardware, but that is an open driver, not a simulator for a missing Mali device. If the target is a new host OS port, Panfrost may be a candidate after checking H616 display-controller support; it does not make QEMU expose the printer's existing G31 hardware interface. QEMU's 2D virtio-gpu backend instead expects a software renderer for 3D, while its VirGL backend translates guest OpenGL calls for host-side rendering. [QEMU virtio-gpu documentation](https://www.qemu.org/docs/master/system/devices/virtio/virtio-gpu.html), [Mesa Panfrost documentation](https://docs.mesa3d.org/drivers/panfrost.html), and Arm's [Fast Models GRM documentation](https://documentation-service.arm.com/static/5f48caef6e73485d721e9790) describe these distinct approaches.

The experiments were offline or read-only with respect to the printer. No update, bootloader, partition, or MCU write was performed.
