# CXLINE v2 container: static writer/reader map

## Status and provenance

This is a static reconstruction of the PioCreat `cxdlp.dll` CXLINE v2 writer and reader. It is detailed enough to guide an inert parser, but it is **not yet validated against a `.cxline` sample**. A search of the current workspace found no such sample. The private installer and DLL are not copied into this public repository.

| Artifact | Provenance | SHA-256 |
|---|---|---|
| PioCreat Box installer `4.6.0.3918` | [PioCreat official files host](https://files.piocreat3d.com/official/software_versions/ba81ce5e9cee4089bb002d824a88647a.exe); installer retained privately | `5221940e06d9f38396eed3a37a1de69466cf4889e2942091c98480cb15ac3c53` |
| `cxdlp.dll` extracted from that installer | Private research archive | `f6b0af46a5d16ea9b2ab8bab2817246173b942712b7d4923c33230e18eb117c8` |

The vendor's [software center](https://www.piocreat3d.com/software) is the public provenance page. The function addresses below are RVAs in this exact DLL build, not file offsets or addresses from the printer firmware.

## Serialization primitives

- `FileWrite << std::string` writes a 32-bit length equal to `string.size() + 1`, the string bytes, and a trailing NUL. On this x86-64 Windows build the length is little-endian. For example, the eight-character `CXLINEV2` marker is encoded as `09 00 00 00 43 58 4C 49 4E 45 56 32 00`.
- `writeStdStringAsQAnsic` is a different representation: a 32-bit byte length of `2 * string.size()`, followed by each input byte expanded to a two-byte unit. The corresponding reader consumes two-byte units and retains the low byte. The writer's character conversion beyond that byte expansion is not established.
- Integer and float operators use the DLL's byte-order selection. In this x86-64 build ordinary primitives are emitted little-endian. The separator is an explicit exception: `0x0a0d` is written big-endian, so the bytes are `0A 0D`.
- `DlpImage` payloads are written as raw bytes, followed by that two-byte separator.

## File order

The wrapper selects file type 12 and the `DlpV2LineHeader::tag` (`CXLINEV2`). The recovered writer order is:

1. Length-prefixed `CXLINEV2` marker.
2. `DlpV2Header`.
3. `DlpParameters`, including a reserved per-layer area table.
4. Four-word image parameter block and separator.
5. One path record per layer, each followed by a separator.
6. At close, the writer seeks back and fills the area table, seeks to EOF, writes a second length-prefixed `CXLINEV2` marker, then appends the checksum.

This is serialization order, not a promise that every reader accepts malformed, reordered, or partially written files. The matching reader dispatches on `CXLINEV2`, reads the v2 line header, then the DLP parameters and image parameters; its path-reading methods are separate.

## Header and image payloads

`writeDlpV2Header` serializes these fields in order:

1. One 16-bit value from header object offset `+0x00`.
2. One ordinary length-prefixed string from header object offset `+0x08`.
3. Three 16-bit values from offsets `+0x28`, `+0x2a`, and `+0x2c`.
4. A `CxdlpBackUse` block: two 32-bit integers, one float, one 32-bit integer, one 16-bit integer, four floats, then 30 raw bytes. These members' meanings are not recovered.
5. Three `DlpImage` byte blocks located in the header object at `+0x80`, `+0x98`, and `+0xb0`. Each writes `DlpImage::size()` bytes and then `0A 0D`. `DlpImage::size()` is `width * height * pixelType` for the stored integer fields; the pixel-type enum's meaning and values are not recovered here.

The object offsets above identify source members used by the writer. They are not absolute file offsets: the ordinary string has variable length, and the blocks are serialized field by field.

## Parameters and delayed area table

The `DlpParameters` writer emits three QAnsic strings, then eleven 16-bit values. It records the current file position and reserves `4 * layer_count + 2` bytes for the per-layer area values and their separator. At close, the writer seeks back to this position, writes one 32-bit value per layer, writes `0A 0D`, and restores the end position.

The wrapper's string-key parser maps these values to:

| Key | Writer member |
|---|---:|
| `exposure_time` | first 16-bit word |
| `light_off_delay` | second |
| `first_exposure_time` | third |
| `first_layer_count` | fourth |
| `first_lift_distance` | fifth |
| `first_lift_speed` | sixth |
| `lifting_distance` | seventh |
| `lifting_speed` | eighth |
| `retract_speed` | ninth |
| not identified | tenth and eleventh |

The map-based wrapper initializes the final two words to zero and has no string key for them. The numeric key parser stores an integer in 32-bit wrapper storage, while the file writer serializes the low 16 bits. The `layer_height` key is formatted into DLP string metadata; which of the three QAnsic strings receives it is still unresolved. `machine_name` is passed to `DlpFileStructure::setMachineType`; its precise serialized header slot is not named by the recovered code.

The separate image parameter block writes four 16-bit values and `0A 0D`. `setDlpLineV2Param` copies, in order, `zthrough_deep_value`, `anti_aliasing`, `minimum_grayscale`, and `maximum_grayscale` into those words.

## Per-layer path record

`CxLineV2WriteWrapper::setLayerPath` calls `CxdlpWrite::writeLayerPath` with the optional third-coordinate flag clear. For each layer the writer emits:

1. One 32-bit scalar. The wrapper supplies `trunc(input_double / 1000.0)` converted to a 32-bit value. Its physical meaning and units are unknown.
2. A 32-bit path-group count.
3. For each group, a 32-bit point count, followed by two 32-bit words for each `Vec3i` point (members 0 and 1). The wrapper does not request the optional third word.
4. The `0A 0D` separator.

The writer emits the point members through unsigned 32-bit operators. The reader consumes the corresponding four-byte slots through `float&` stream overloads before placing values into its path structures; the code establishes the byte width and record shape, but this mixed API typing is another reason to compare a real file before assigning coordinate semantics. The two point words are not assigned names or units here: coordinates, sign treatment, origin, and rasterization rules need a real file and image comparison. The independent per-layer 32-bit area values are written into the reserved table, not into this path record.

## Checksum

`CheckSum::getFileVersionInfo` recognizes the eight-byte `CXLINEV2` tag and selects checksum type 2. `appendFileSum` routes type 2 to `appendFileSumCrc32`; the CXLINE writer calls this after writing its terminal marker.

The static implementation reads the bytes present before the checksum append and updates a table-driven reflected CRC using polynomial `0xEDB88320`. The accumulator starts at zero, and the code does not apply an initial or final `0xffffffff` XOR. It appends the resulting value as a 32-bit primitive (little-endian on this build). This differs from the common zlib `crc32` convention. The algorithm and dispatch are recovered from code, but have not been cross-checked against an emitted CXLINE file.

## Port implications and remaining work

This format is independent of the already implemented CXDLP v2/v3 vertical-run image parser. A CXLINE path needs a separate bounded container reader, path-to-raster conversion, optional distortion/calibration/blur handling, Z-through-depth transform, and a separate exposure/status transaction. It cannot safely be routed through the current CXDLP adapter based on its filename.

Before implementing the parser as a production input, obtain one representative `.cxline` file and compare a byte-for-byte parse against the writer map. The fixture should include its source project or slicer settings if available, layer count, dimensions, and a known asymmetric layer. Then verify string lengths, all section boundaries, the last area entry, trailer marker, CRC bytes, path coordinate range/origin, and reconstructed intermediate images. Until that comparison, the field meanings, image-block roles, rasterization, calibrations, and compatibility with the active 540x2560 BGRA panel sink remain open.

### Static references in `cxdlp.dll`

| Routine | RVA | Recovered role |
|---|---:|---|
| `CxdlpRead::readDlpV2Header` | `0x10810` | Reads CXLINE v2 header fields and image blocks |
| `CxdlpRead::readDlpParameters` | `0x10a40` | Reads parameter strings/words and area table |
| `CxdlpWrite::writeDlpV2Header` | `0x17f50` | Writes v2 header and image blocks |
| `CxdlpWrite::writeDlpParameters` | `0x18110` | Writes parameters and reserves area table |
| `CxdlpWrite::writeDlpImageParam` | `0x17ef0` | Writes four image parameter words |
| `CxdlpWrite::writeLayerPath` | `0x189e0` | Writes a path layer record |
| `CxdlpWrite::writeLayerAreasDealyer` | `0x188e0` | Backfills the delayed area table |
| `CxdlpWrite::writeTail` | `0x18db0` | Writes terminal tag and appends checksum |
| `CxLineV2WriteWrapper::writeDlpStructure` | `0x1b9a0` | Writes structure, then image parameters |
| `DlpLineV2ParamWrapper::setVal` | `0x1ac30` | Maps string keys to parameter members |
| `CheckSum::getFileVersionInfo` | `0x4c80` | Selects type 2 for `CXLINEV2` |
| `CheckSum::appendFileSumCrc32` | `0x3c00` | Calculates and appends the 32-bit checksum |
