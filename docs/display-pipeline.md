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
    U[STM32 control UART: M678/status] -. separate control path .-> P
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

Thus each 32-bit output pixel carries three adjacent one-byte layer samples. The RGB channel values preserve three independent exposure intensities while the horizontal frame width falls from 1620 to 540. The byte-level transform is recovered from code; which output channel reaches each physical LCD column, and whether a later block reverses the order, remain open. `MirroredX=true` is in the profile, but its application point was not found in this transform.

The alternate non-compressed path is different: it reads one source sample per output pixel, repeats it into the three color bytes, and sets alpha to `0xff`. The active CL60 profile selects the compressed path above.

## Display backend and synchronization

For the CL60 profile, `YuvDataSend::init` constructs the generic `CreateVideoOutport` backend. It does not take the model-dependent `CreatevDlpOutport` branch used by other Creality products.

The statically recovered `libuapi` backend:

1. Opens `/dev/disp` read/write and obtains display dimensions with ioctls `7` and `8`.
2. Requests a display layer and initializes its configuration through ioctl `0x47`.
3. Allocates one display buffer through the Sunxi ION adapter for the active PrinterUI path. It copies the converted frame into that buffer, synchronizes the written range for display, and submits the layer configuration through `DispQueueToDisplay` (vtable slot `+0x10`), which uses ioctl `0x47`.
4. PrinterUI sets layer z-order to `1` (slot `+0x24`) and enables the layer (slot `+0x14`). The generic backend also exposes `DispWriteData` (slot `+0x08`), but the active CL60 path queues the layer directly and does not call that method. The active path does not show alternating frame buffers.

Live kernel output independently shows H616 HDMI at 540×2560 reaching the RK628 at I²C2 address `0x50`, then MIPI DSI1 initialized with four lanes at 840 Mb/s each. The I²C0 `cxsw,dlp1438` path is not active for this unit; its probe rejects the product. The operator GUI is separate: it uses `/dev/fb0` at 800×480 RGB24.

The recovered layer loop has separate display-result and MCU-control paths. PrinterUI submits the frame with `SendBgraImage`. In the active print call path, `waitExposureResult` polls `waitExposureEnd` about every 220 ms while the backend returns code `4`; code `2` causes one retry after a one-second delay, and `doExposure` treats code `5` as success. The similarly named `waitExposureFinished` method exists, but its backend calls do not by themselves establish a vblank or frame-complete event, and it is not the active `doExposure` polling call identified in the main CL60 path. The precise meaning and producer of these result codes remain unresolved.

Separately, the UI sends `M678` over UART, waits for its matching reply and motor status, then polls `M114` before calling `openLight` (`M42 P36 M1 S0`). The STM32's M678 worker sets the event bit that M114 can consume as `M114_DELATLIGHT_OVER`. This strongly suggests an MCU phase gate before light-on, but no passive layer trace has confirmed the exact reply accepted by PrinterUI. The MCU status replies do not report the display backend's exposure completion.

### Backend alternatives not selected by CL60

The `CreatevDlpOutport` backend is present for other product profiles but is not selected by the active CL60 configuration. Its `vDlpOutDisplay` method builds a 10-byte header (`04 60 02 00 F1 00 00 40 38 00`), appends the image and a big-endian CRC16 computed over header plus payload (initial value `0`, polynomial `0x1021`, no reflection/final XOR), then performs ioctl `0x40016bc8`, `write`, and ioctl `0x40016bc9`. A separate `vDlpOutSendPhoto` path uses CRC16-CCITT-FALSE initialized to `0xffff` over the payload only, and writes the packet without that ioctl pair. These are recovered alternative backend protocols, not the active CL60 panel transport.

### Frame storage sizes and unresolved stride

For the active compressed profile, the one-byte source frame contains `1620 × 2560 = 4,147,200` bytes. The converted `540 × 2560` BGRA buffer contains `5,529,600` bytes; tightly packed output rows are `540 × 4 = 2,160` bytes. The conversion and copy sizes support this dense layout, but PrinterUI's code does not use `QImage::bytesPerLine()` in the reviewed copy path. The actual display driver's scanout stride/alignment is therefore not confirmed by this userspace analysis.

## Remaining physical evidence

- Trace the DSI1 FPC from the RK628 to the exposure panel and record connector orientation/pin mapping.
- Determine the panel's actual row/column address direction and channel-to-column order using a known test image or passive DSI capture.
- Locate the point where `MirroredX=true` is applied in the image parser or display pipeline.
- Identify the producer and exact meaning of display result codes 2, 4, and 5, and whether any backend/kernel wait corresponds to frame completion or vblank.
- Confirm scanout stride/alignment from the `/dev/disp` driver and identify whether the queued layer change takes effect at a frame boundary.

No test bitmap was displayed and no light, motor, or STM32 command was triggered for this analysis.
