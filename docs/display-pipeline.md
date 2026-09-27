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
3. Allocates display memory through the Sunxi ION adapter. `DispWriteData` copies the frame into one of two buffers, flushes the written range, and submits the updated layer configuration through ioctl `0x47`.
4. Lets PrinterUI enable or disable the layer through backend calls. The exposure wait function calls backend synchronization/status methods and checks a result value; the exact virtual-method names and the RK628's frame-complete signal are not resolved.

Live kernel output independently shows H616 HDMI at 540×2560 reaching the RK628 at I²C2 address `0x50`, then MIPI DSI1 initialized with four lanes at 840 Mb/s each. The I²C0 `cxsw,dlp1438` path is not active for this unit; its probe rejects the product. The operator GUI is separate: it uses `/dev/fb0` at 800×480 RGB24.

## Remaining physical evidence

- Trace the DSI1 FPC from the RK628 to the exposure panel and record connector orientation/pin mapping.
- Determine the panel's actual row/column address direction and channel-to-column order using a known test image or passive DSI capture.
- Locate the point where `MirroredX=true` is applied in the image parser or display pipeline.
- Recover exact frame/vsync synchronization semantics from the backend and kernel driver.

No test bitmap was displayed and no light, motor, or STM32 command was triggered for this analysis.
