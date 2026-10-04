# Exposure display data path

## Recovered route

The layer bitmap does not travel over the STM32 UART. PrinterUI sends small control/status commands over `/dev/ttyS2`; it submits the much larger exposure frame through the H616 display stack.

```mermaid
flowchart LR
    J[CXDLP or CXLINE layer] --> P[PrinterUI layer parser]
    P --> S[1620 × 2560 one-byte samples]
    S --> C[writerClearImage: groups of 3]
    C --> B[540 × 2560 BGRA frame]
    B --> I[ION buffer and cache flush]
    I --> D[/dev/disp layer, ioctl 0x47]
    D --> H[H616 HDMI output]
    H --> R[RK628 receiver, I²C2 0x50]
    R --> M[MIPI DSI1, 4 lanes]
    M --> L[Monochrome exposure LCD]
    U[STM32 control UART: M678/status] -. layer/motor control .-> P
```

The last panel node is the product's monochrome exposure LCD. The route from the RK628 through DSI1 is confirmed by the live device tree and kernel logs. The exact panel connector pinout and the bridge's final physical column mapping have not been probed.

## Active profile and pixel packing

The installed `/usr/bin/PrinterUI/halotMachine.xml` contains the active `CL60`/`HALOT-ONE` profile with these relevant values:

| Profile field | Value |
|---|---|
| `PrinterStyle` / `SendImageType` | `LCD` / `LCD` |
| `SerialName` / `SendSerialModelType` | `ttyS2` / `E` |
| `RgbRange` | `BGRA` |
| `MirroredX` / `IsHorizontal` | `true` / `true` |
| `OriginalResolution` | 1620 × 2560 |
| `IsCompress` / `CompressResolution` | `true` / 540 × 2560 |

Static analysis of `YuvDataSend::writerClearImage` (`PrinterUI`, `0x00210750`) establishes the active transform. It treats the source raster as one-byte samples with a row stride of 1620. For output coordinate `(x,y)`, where `0 ≤ x < 540`, it reads source samples at:

```text
source index = y × 1620 + 3 × x
samples      = source[index], source[index + 1], source[index + 2]
```

For the `BGRA` profile it writes those samples in reverse byte order and appends opaque alpha:

```text
output bytes = sample[2], sample[1], sample[0], 0xff
```

Thus each 32-bit output pixel carries three adjacent one-byte layer samples. The RGB channel values preserve three independent exposure intensities while the horizontal frame width falls from 1620 to 540. The byte-level transform is recovered from code; which output channel reaches each physical LCD column, and whether a later block reverses the order, remain open. `MirroredX=true` is in the profile, but its application point was not found in the active CL60 LCD transform. A separate `QImage::mirrored` call exists in `genarateBmp`'s DLP/mask path (`PrinterUI` near `0x001bce20`); no call-path evidence connects that helper or its config byte to active CL60 `lcdPrint`.

`sendImageDataToHdmi` copies the converted QImage into the ION buffer without another userspace channel permutation. That bounds the known software transform through `/dev/disp`; it does not prove that the H616 HDMI output or RK628 converts color components unchanged before the monochrome panel.

The alternate non-compressed path is different: it reads one source sample per output pixel, repeats it into the three color bytes, and sets alpha to `0xff`. The active CL60 profile selects the compressed path above.

## Display backend and synchronization

For the CL60 profile, `YuvDataSend::init` constructs the generic `CreateVideoOutport` backend. It does not take the model-dependent `CreatevDlpOutport` branch used by other Creality products.

The statically recovered `libuapi` backend:

1. Opens `/dev/disp` read/write and obtains display dimensions with ioctls `7` and `8`.
2. Requests a display layer and initializes its configuration through ioctl `0x47`.
3. Allocates one display buffer through the Sunxi ION adapter for the active PrinterUI path. It copies the converted frame into that buffer, synchronizes the written range for display, and submits the layer configuration through `DispQueueToDisplay` (vtable slot `+0x10`), which uses ioctl `0x47`.
4. PrinterUI sets layer z-order to `1` (slot `+0x24`) and enables the layer (slot `+0x14`). The generic backend also exposes `DispWriteData` (slot `+0x08`), but the active CL60 path queues the layer directly and does not call that method. The active path does not show alternating frame buffers.

Live kernel output independently shows H616 HDMI at 540×2560 reaching the RK628 at I²C2 address `0x50`, then MIPI DSI1 initialized with four lanes at 840 Mb/s each. The I²C0 `cxsw,dlp1438` path is not active for this unit; its probe rejects the product. The operator GUI is separate: it uses `/dev/fb0` at 800×480 RGB24.

The image path and MCU layer-control path are separate. In the active CL60 configuration, `SerialPortPrintFile::run` dispatches to `lcdPrint` and that function does not call `waitExposureResult`, `waitExposureEnd`, or `doExposure`. The DLP-oriented paths do call these helpers: `waitExposureResult` (`0x0027e6f4`) polls `waitExposureEnd` (`0x001c0248`), which reaches `YuvDataSend::waitExposureFinished` (`0x00211f64`). This method always dispatches through a separate DLP handle, not the generic Video handle used by CL60. In the DLP backend, vtable slots `+0x1c` and `+0x24` read print status and total frames; the driver obtains a 9-byte reply from the DLP I²C device, with status at byte 0, total-frame count at bytes 5–6, and exposed-frame count at bytes 7–8. The status getter reads the chip-specific `dlp_status` sysfs attribute. The wrapper polls about every 220 ms while the returned status is `4`, retries once after a one-second delay for `2`, and the DLP exposure path accepts `5` as success. These codes and this status path describe the alternate DLP backend; they are not evidence of CL60 frame completion.

For CL60, the `lcdPrint` CXDLP branch submits the current decoded frame with `SendBgraImage` (near `0x00274d64` / focused decompilation lines 42427–42443), sends its prepared `M678` request, increments the layer index, and starts parsing the next CXDLP layer before it waits for the current UART/M114 cycle (lines 42443–42511). The parser-ready flag gates the next loop iteration, so this is one-layer decode prefetch: the next frame is not submitted before the current layer's `M114_OK` completes. `WaitMotorStatus` sends framed `M114` queries about every 220 ms while its polling flag is clear. `CXSerial::getRecvTypeAndMsg` splits response lines on `_`, so raw `M114_OK` becomes map key `M114` and value `OK\n`; the synchronous receive helper returns that value, and `WaitMotorStatus` compares it byte-for-byte with `OK\n`. This matches the live PrinterUI log (`strCmd M114`, `strMsg "OK\n"`) and the success path that advances the layer. Completed post-print traces record all 1,591 and all 1,750 M678 layer cycles; each is followed by M678_Busy, M114_DELATLIGHT_OVER, and M114_OK before the next frame is submitted. In the 1,750-layer trace, every cycle completed before the stock UI exited the print state. The LCD loop does not call `openLight`; the STM32 worker's actual light timing remains unmapped. The DLP-specific `doExposure` path sends `M114`, then calls `openLight` (`M42 P36 M1 S0`), and subsequently polls the DLP output status.

### `/dev/disp` queue and synchronization

The active userspace call submits a layer configuration, not the image bytes, through `/dev/disp` ioctl `0x47`. The libuapi wrapper builds a one-record request; kernel `disp_ioctl` accepts up to 16 records and copies each 184-byte configuration into kernel staging memory before dispatching it to the selected display manager. The BGRA bytes are already in the external ION-mapped buffer referenced by the layer's plane address. `sendImageDataToHdmi` allocates that buffer once and reuses the same mapped address for later frames, copying and cache-flushing each new raster before queuing its layer record. This proves single-buffer reuse in the inspected userspace path. It leaves open whether the display engine can still be scanning that buffer during the next copy; tearing is a possible consequence, not an observed fault.

The kernel has display RCQ enabled. The VSYNC IRQ path updates scanline/timing counters and wakes a thread that emits a uevent, but the recovered call chain does not show it applying the queued layer configuration or completing the userspace ioctl at VSYNC. `disp_mgr_sync` returns early with RCQ enabled, and `disp_al_manager_sync` is a stub in this build. Register updates are visible on force-apply/enable paths, not as a demonstrated per-frame VSYNC commit. Therefore the exact point at which a newly queued exposure frame becomes visible, and whether the change is atomic at a frame boundary, remain unresolved.

### What the passive live trace exposes

The completed 2026-10-04 passive `strace` capture includes the full 1,750-layer job, UART, `open`/`close`, `ioctl`, `mmap`/`munmap`, and display-buffer synchronization calls. It records `/dev/mali0` activity and `/dev/fb0` `FBIOGET_VSCREENINFO`/`FBIOPAN_DISPLAY` calls, while the captured process mappings show shared Mali regions. The full trace confirms 14,000 `/dev/disp` calls before the 1,750 M678 requests: 7,000 GET_CONFIG (`0x48`) and 7,000 SET_CONFIG (`0x47`), or four GET/SET pairs per layer. All returned success. It also records 1,750 successful ION sync requests (`0x05`) plus one ION buffer-map request. These calls confirm the software transaction pattern, but ioctl pointers and arguments do not expose the BGRA bytes. `strace` cannot observe CPU stores through an existing `mmap`; the exposure pixels themselves remain uncaptured, and the capture does not prove which values reached the RK628.

An interim 16 MiB window at 13:25:43 UTC showed 14 valid UART layer frames aligned to zero-based job layers 1,204–1,217 after matching each `L` token against the captured job's area table. The frames used regular-layer `P4200/M1000` values. The final full capture later confirmed all 1,750 layer joins and the same absence of mapped pixel bytes.

The live `PrinterUI` fd and map snapshots add a concrete buffer identity: one ION-exported `/dmabuf` has `fdinfo` size 5,529,600 bytes and a shared mapping of the same length, exactly the active 540×2560×4 BGRA frame size. A second ION dma-buf is 3,072,000 bytes and is not yet identified. In a six-layer syscall window (12:13:18–12:14:02 UTC), each `M678` is preceded by one ION ioctl `0x05` and four repeated `/dev/disp` ioctl `0x48`/`0x47` pairs. All six ION sync calls and all 48 display calls returned success; the four pairs are tightly grouped before the corresponding 101-byte UART command. The libuapi wrappers show that `0x48` retrieves a display-layer configuration and `0x47` writes the modified configuration back. The wrapper functions separately modify layer z-order (`DispSetZorder`), screen destination rectangle (`DispSetRect`), enable state (`DispSetEnable`), and source crop (`DispSetSrcRect`). `DispWriteData` copies the supplied image into the selected output buffer and calls the same get/modify/set helper to submit the buffer descriptor. Allwinner's published [sunxi display2 UAPI header](https://github.com/allwinner-zh/linux-3.4-sunxi/blob/master/include/video/sunxi_display2.h) independently assigns `0x47`/`0x48` to layer SET/GET_CONFIG and defines a config containing layer info plus enable, channel, and layer ID; this is a cross-check, not proof that the H616 Tina kernel uses that exact source revision. The trace therefore shows configuration updates rather than four image payloads, but it does not reveal which wrapper corresponds to each live pair, the structure values, or why four updates occur per layer.

A fresh interim window confirmed that same order on zero-based captured-job layers 1,211 and 1,212. The ION sync call beginning at 13:25:33.806805 returned 0 at 13:25:33.807774; four `/dev/disp` GET/SET pairs then all returned 0, with the last SET returning at 13:25:33.857859. The 101-byte UART write began at 13:25:33.888443. The next layer repeats the pattern: the ION sync call at 13:25:42.558853 returned 0, four successful GET/SET pairs ended at 13:25:42.600674, then the M678 write began at 13:25:42.613577. The final display ioctl returned about 31 ms and 13 ms before those respective UART writes. The full trace subsequently confirmed the same 8-call pattern for all 1,750 frames. This is syscall-level evidence that the host queues the display configuration before requesting STM32 layer work. It still does not show the BGRA bytes or prove when the panel scans the new buffer.

A read-only attempt to snapshot the mapped dma-buf through `/proc/<pid>/mem` returned `EIO`; `process_vm_readv` returned `EFAULT` for that mapping. Ordinary process pages remain readable through `/proc/<pid>/mem`. The kernel exposes the buffer mapping and size but these generic process-memory readers did not retrieve its pixel bytes during the active trace. Thus the live image data itself remains uncaptured.

A later live `/proc` inspection confirmed that the mapping is the active ION
dma-buf: its shared mapping and fdinfo size are both 5,529,600 bytes, matching
the complete 540×2560 BGRA frame. A separate `pread64` attempt against the
mapping still returned `EIO`, and opening the anonymous dma-buf through
`/proc/<pid>/fd/<n>` returned `ENXIO`; it does not provide a normal byte-stream
read interface. In the same print, the host log records `SendBgraImage`
completion for one layer, `M114_DELATLIGHT_OVER`, then `M114_OK`, then the next
`SendBgraImage`. This adds live confirmation of buffer identity and submission
ordering, but no frame-byte or panel-scanout evidence. The detailed private
attempt log is kept outside this documentation checkout.

The operator display is explicitly `/dev/fb0` at a logical 800×480 RGB24. A read-only runtime snapshot exposes a single `/sys/class/graphics/fb0` backed by the Allwinner `disp` driver, with `virtual_size=800,960` and `bits_per_pixel=32`; `/proc/fb` is empty. The difference between the visible UI dimensions and the virtual framebuffer allocation is not resolved here. The exposure frame uses the separate ION + `/dev/disp` route above. Therefore `FBIOPAN_DISPLAY` is operator-UI framebuffer activity, not an exposure-panel update.

For the active CL60 frame, PrinterUI supplies dimensions 540×2560, format `0x0e`, and alignment/stride field `0`. `libuapi` maps that format to kernel format `0x43`, which the display engine classifies as 32 bits per pixel. The active layer setup passes width into the driver; with alignment field zero, the driver's pitch calculation is dense: `540 × 4 = 2160` bytes per row. The complete output frame is `2160 × 2560 = 5,529,600` bytes, exactly the userspace conversion/copy length. This establishes the submitted buffer's stride; it does not identify the bridge's internal sampling or physical panel column mapping.

### Backend alternatives not selected by CL60

The `CreatevDlpOutport` backend is present for other product profiles but is not selected by the active CL60 configuration. Its `vDlpOutDisplay` method builds a 10-byte header (`04 60 02 00 F1 00 00 40 38 00`), appends the image and a big-endian CRC16 computed over header plus payload (initial value `0`, polynomial `0x1021`, no reflection/final XOR), then performs ioctl `0x40016bc8`, `write`, and ioctl `0x40016bc9`. A separate `vDlpOutSendPhoto` path uses CRC16-CCITT-FALSE initialized to `0xffff` over the payload only, and writes the packet without that ioctl pair. These are recovered alternative backend protocols, not the active CL60 panel transport.

### Frame storage sizes and stride

For the active compressed profile, the one-byte source frame contains `1620 × 2560 = 4,147,200` bytes. The converted `540 × 2560` BGRA buffer contains `5,529,600` bytes with a confirmed dense output pitch of 2,160 bytes per row. The alignment field is explicitly zero in this call path, so the kernel's optional pitch-rounding branch is not used. This conclusion comes from the active userspace layer descriptor and the matching format/pitch calculation in the display driver.

## Remaining physical evidence

- Trace the DSI1 FPC from the RK628 to the exposure panel and record connector orientation/pin mapping.
- Determine the panel's actual row/column address direction and channel-to-column order using a known test image or passive DSI capture.
- Establish a way to hold both UV and motion inactive before any test image is submitted. The stock `lcdPrint` path couples image submission to an `M678` layer command; Odyssey's `ManualDisplayLayer` writes the separate operator framebuffer and is not a safe exposure-panel test path.
- Locate the point where `MirroredX=true` is applied in the image parser or display pipeline.
- Determine the exact meaning of DLP result codes 2, 4, and 5, and whether the DLP backend/kernel wait corresponds to frame completion or vblank.
- Recover the effective runtime DSI timing override state; the compiled CL60R/type-1 default is 540×2560 at 112 MHz, but the corresponding sysfs read returns `EIO`.
- Identify whether the queued layer change takes effect atomically at a frame boundary; the ioctl/RCQ path does not expose a confirmed userspace VSYNC wait.

No test bitmap was displayed and no light, motor, or STM32 command was triggered for this analysis.
