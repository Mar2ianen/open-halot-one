# Firmware package, updater, and boot path

## Downloaded package identity

The archive found in the owner's Downloads folder is:

`V1_H2.303.1a2.303.1_C2.302.4_R2.302.1.tar.gz`

| Item | Value |
|---|---|
| Archive size | 130,952,309 bytes |
| SHA-256 | `fd50ea42c1f29ea7e79618c5a80a325a51c9658160e5d6e257df5ae067e14c2e` |
| Contents | `configUpdate.ini` and `cx7_v2.303.1_APP_v2.303.1_Beta.swu` |
| `.swu` size / SHA-256 | 147,343,360 bytes / `b5775f530b6d9bc5bcbe82d9681c45064536500430621e0cea701bc89e93b422` |
| `configUpdate.ini` integrity value | MD5 and `swrMd5Value` both `2ea28f26cc4ce70baece4ce2ab3c4843` |

The `.swu` is a CPIO SVR4 CRC archive with five top-level entries: `sw-description`, `recovery`, `uboot`, `kernel`, and `rootfs`. It has no separate top-level STM32 image. Its inner SquashFS rootfs does contain `/etc/V1-01.bin` (33,236 bytes; SHA-256 `a950f58db8382c5673b12ee81cd2ebb4833832aa1e226829bd61a1c29d7d7c02`) and `/usr/bin/mcu_tool` (17,840 bytes; SHA-256 `221a9c20825dc601ae9c43e18fb813be49a9a1d6e2ed06be4b696a2a341308d3`). The MCU image is a Cortex-M binary with initial stack pointer `0x20004460` and reset handler at `0x0800019c` (the vector entry includes the Thumb bit); its strings include `SWV1.89`. The exact STM32 part number is not recoverable from these facts alone.

The CPIO members and SquashFS report creation timestamps of 2023-09-04. In the owner's screenshot of the [Creality Cloud HALOT-ONE firmware list](https://www.crealitycloud.com/ru/downloads/firmware/halot-series/halot-one?source=1), this exact filename is the first entry, dated 2023-09-21; the older versions appear below it. The archive's `recovery`, `kernel`, and `rootfs` payloads compare byte-for-byte equal to the first 20,625,408 bytes of `p4`, the first 13,484,032 bytes of `p5`, and the first 111,935,488 bytes of `p6`, respectively; the STM32 image inside that matching rootfs is therefore the installed copy too. The device already ran software version `2.303.1`. The package also contains a separate `uboot` member; because its exact installed counterpart and write destination remain unresolved, we cannot determine whether that bootloader payload differs from the unit's current one.

### Audit of Creality.com's 2026 firmware card

The [Creality.com HALOT-ONE download page](https://www.creality.com/download/creality-halot-one-resin-3d-printer) rendered a firmware card dated Sep 29, 2026, but inspection of its server-rendered page data found `firmwareList:[]`. The page's component takes the first element of this array, then passes its `version`, `releaseTime`, and `downloadUrl` to the card. With an empty list these values are undefined; the date component formats the missing release time as the current date, while its download handler only creates a download link when the URL is present. That explains the changing Sep 28/Sep 29 card date and blank version/title: it is a UI placeholder, not evidence of a new firmware release. The [page component bundle](https://www.creality.com/_next/static/chunks/app/%5Blocale%5D/download/%5Bhandle%5D/page-de52f522c050668f.js) supplies the firmware list to the card, and the [shared UI bundle](https://www.creality.com/_next/static/chunks/common-6bb518caa1868db5.js) contains the first-item selection and guarded download logic. The separately displayed Cloud firmware list in the owner's screenshot remains the only identified HALOT-ONE package listing in this investigation; its newest entry is the 2023-09-21 `2.303.1` archive above.

No stable direct CDN URL for this exact archive was exposed during inspection; use the Creality Cloud list above to reach the download entry.

## Earlier official 2.238.2 package and STM32 image

The shared HALOT archive `V1_H2.238.2a2.238.2_C2.238.2_R2.238.2.tar.gz` is available from the [official Creality CDN](https://file2-cdn.creality.com/file/63c45268ee001da26529f5f3629f7834/V1_H2.238.2a2.238.2_C2.238.2_R2.238.2.tar.gz). Its 130,822,607-byte archive has SHA-256 `b80147dcd1f47d8124bef7b90d9cd6c23ce2af3f16c78a16b7ed737d94c31d57`; the 147,277,824-byte SWU member has SHA-256 `1f4e6d70486894f004c0e839d22e18c7bc2feaf0fbeb92a072050da5964b845e`. Its rootfs is 111,804,416 bytes.

The rootfs contains `/etc/V1-01.bin`, 31,248 bytes with SHA-256 `379470dd8afe47b152cabdedcd6c983b1fc112c07d164a18d8d0fbb89677f319`; its vector table gives initial SP `0x20004448` and reset vector `0x0800019d` (Thumb code at `0x0800019c`), and its strings identify it as `SWV1.821`. Static Thumb references resolve the `M800`/`M355` command and reply strings to dispatcher instructions. The `M800 S0` branch calls code at `0x08004070`; the `M355` path builds and sends a 10-byte packet, waits 500 ms, sends 3 bytes, and waits another 500 ms. USART3 (`0x40004800`) and DMA1 (`0x40020000`) literal references are also present. Its `mcu_tool` is byte-identical to the later 2.303.1 package's helper (17,840 bytes, SHA-256 `221a9c20825dc601ae9c43e18fb813be49a9a1d6e2ed06be4b696a2a341308d3`). The STM32 image was streamed from the public archive for hashing and static comparison; the vendor binary is not stored in this project. Unlike the later unit-matched package, this shared 2.238.2 image is an earlier comparison point, not proof of what was installed on this printer.

## Phased SWUpdate plan

`sw-description` declares Tina firmware version `2.303.1` and a three-stage `swu_mode` sequence:

1. **`upgrade_recovery`** writes `recovery` directly to `/dev/by-name/recovery` and hands the `uboot` member to the Allwinner-specific `awuboot` handler. It sets the next mode to `upgrade_kernel`, selects the recovery boot partition, and requests a reboot.
2. **`upgrade_kernel`** writes `kernel` directly to `/dev/by-name/boot` and `rootfs` directly to `/dev/by-name/rootfs`. It sets `swu_version=2.303.1`, selects `boot`, and advances to `upgrade_usr`.
3. **`upgrade_usr`** clears the SWUpdate parameters and requests a reboot.

There is a commented-out `awboot0` image entry; this package does not provide a separate `boot0` CPIO member. The `awuboot` write destination and its pre-write clearing operation are now mapped in the main SoC boot section below. The top-level CPIO has no separate signature member and `sw-description` has no explicit cryptographic signature/hash directive; the outer config carries MD5 integrity values. This alone does not prove that a modified package would pass the installed SWUpdate/update path.

## STM32 update at OS startup

The rootfs enables `/etc/init.d/stm32_update` as `S21stm32_update`. Its static logic is:

1. Select `/dev/ttyS2` for this product (only `CD60`/`D160` use `/dev/ttyS3`).
2. Run `mcu_tool -u -f /etc/V1-01.bin <UART>` to query product/firmware state. The binary's strings distinguish `new > current` from `new <= current` and log a manufacturer/product mismatch message.
3. If the helper returns `1`, set the H616-side BOOT0 control (`/sys/class/gpio_sw/PA6`) high, assert/deassert reset via `/sys/class/gpio_sw/PA0`, and retry `stm32flash <UART>` up to 60 times.
4. Run `stm32flash -w /etc/V1-01.bin -v -S 0x08000000 <UART>`, then lower BOOT0 and reset the MCU so the application starts.
5. Restore application UART speed to 115,200 baud and write a completion flag.

If no update is required, the script simply resets the MCU through PA0. This is a boot-time updater path, not a separate image in the `.swu` CPIO. The exact return-code conditions inside `mcu_tool` have not yet been decompiled. The ROM-programming sequence was not executed on the printer.

## Main SoC boot and eMMC layout

The saved environment is readable through `fw_printenv`; `/etc/fw_env.config` points to the redundant environment partitions `env` and `env-redund` at offset `0`, with `0x20000` bytes in each. The running kernel command line reports U-Boot version `2018.05-g14fbabb0`. The saved environment contains `bootdelay=0`, `boot_partition=boot`, and `bootcmd=run setargs_nand boot_normal`. Its relevant entries are:

```text
setargs_nand=... root=${nand_root} ...
setargs_mmc=... root=${mmc_root} ...
boot_normal=sunxi_flash read 45000000 ${boot_partition};bootm 45000000
boot_recovery=sunxi_flash read 45000000 recovery;bootm 45000000
boot_fastboot=fastboot
```

The saved command defines a read of the `boot` partition into `0x45000000` followed by `bootm`, but the current boot path is not fully resolved. `fw_printenv` reports `nand_root=/dev/nand0p4` and `mmc_root=/dev/mmcblk0p4`; neither matches the running kernel's `root=/dev/mmcblk0p6`. The running command line contains `boot_type=2`, but `fw_printenv boot_type` reports that variable is not defined in the saved environment. The vendor update manifest and GPT names identify `boot` as p5 and `rootfs` as p6, but that does not prove which U-Boot selection path produced the current command line. With `bootdelay=0`, an interactive U-Boot prompt is not offered through the ordinary delay window; no alternate key or UART interruption path has been tested. The environment was read only.

The same environment capture lists fastboot key values `0x02–0x08` and recovery key values `0x10–0x13`; the physical key-to-value mapping and which copy of the redundant environment is active were not tested. These are captured configuration strings, not proof that a particular key sequence works.

The downloaded `uboot` member is a 1,294,336-byte Allwinner TOC1 package (`SHA-256 75b7f37ad259842c72c505b4ec2289a426b819004298799c4b15bbf24a7544c4`). Its TOC lists `u-boot` (1 MiB), `monitor` (0x182d0 bytes), `dtbo` (0x11c0 bytes), and `dtb` (0x20600 bytes). A byte-for-byte comparison found the complete package in the captured eMMC user area at byte offset `0x01004000` (sector `0x8020`, decimal 16,793,600); it spans 2,528 sectors and ends at `0x0113c000`, before `p1` begins at `0x02400000`. The package's embedded U-Boot version matches the running `2018.05-g14fbabb0` version.

The installed updater is SWUpdate `2019.04.0-rc1`; it links `libota-burnboot.so` (`ota-burnboot` package `0.1-0.1`) and its `install_awuboot` handler calls `OTA_burnuboot`. Static reversal of that library, combined with the live `boot_type=2` and `sunxi_secure: normal` values, resolves this unit's path: the handler selects its SD/eMMC backend, opens `/dev/mmcblk0` read-write, clears a 1 MiB region at byte offset `0x012a6000`, then writes the complete TOC1 package at sector `0x8020` (byte offset `0x01004000`) and calls `fsync`. The package's embedded start-sector field at offset `0x4ec` is zero, so the handler uses its fallback sector value `0x8020`. The cleared 1 MiB region is zero-filled in the captured snapshot; its role is not named in the library, so treating it as a secondary boot copy would be speculation. No updater or write path was executed during this analysis.

The raw user-area prefix also contains Allwinner BOOT0/SPL strings (`u-boot` at offset `0x0000c635` and `HELLO! BOOT0 is starting!` at `0x0000c65c`); their image boundaries and the BootROM's exact selection path are not yet established. The separate 4 MiB eMMC hardware-area captures `boot0` and `boot1` are both entirely zero-filled, and Linux reports both devices read-only (`ro=1`). Therefore the executable U-Boot package observed here is in the user area, not those two hardware areas. `p1` is FAT16 with boot-logo assets and `magic.bin`, despite its GPT label `bootloader`; `p2`/`p3` hold the redundant U-Boot environments; `p4` is recovery; `p5` is the normal kernel boot image; `p6` is the read-only SquashFS rootfs; and `p7` is the writable ext4 overlay. RPMB was not read.

## Could a custom, newer kernel boot?

**Technically plausible, not yet demonstrated.** This unit has root access, a readable eMMC partition map, a vendor update plan that directly installs an Android boot image and rootfs, and a saved U-Boot environment that names `boot` and `bootm`. The vendor package targets the `boot` and `rootfs` partitions, but the environment-to-live-command-line mismatch means the exact boot selection still needs to be explained. These facts identify the vendor update targets for a replacement image; they do not prove that an arbitrary image will boot or that a recovery path will work.

The H616 is represented in the upstream Linux tree, including its SoC device tree and peripheral drivers ([upstream H616 DTS](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/allwinner/sun50i-h616.dtsi)). That establishes SoC-level mainline support, not a ready-to-boot HALOT-ONE image. A newer kernel still needs the correct board device tree, storage/PMIC configuration, boot-image packaging compatible with this U-Boot, and working printer display, touch, RK628, and CXSW-specific paths. The existing Qt UI also expects vendor interfaces such as `/dev/disp` and `/dev/ion`.

The vendor package has no visible signature member, but no modified package was prepared or offered to SWUpdate. The updater's own secure-mode branch reports `sunxi_secure: normal` on this unit; that does not establish every BootROM or U-Boot image-acceptance policy. Active environment-copy selection, recovery under a malformed boot image, and a tested rollback path remain unknown. No partition, environment, MCU, or boot area was written or altered as part of this analysis.

## Private artifacts and source links

The original archive remains in the owner's Downloads folder. Extracted MCU bytes and analysis files are private local artifacts; the public repository contains hashes and findings only.

- [Creality HALOT-ONE downloads](https://www.creality.com/download/creality-halot-one-resin-3d-printer)
- [Creality Cloud HALOT-ONE firmware listing](https://www.crealitycloud.com/ru/downloads/firmware/halot-series/halot-one)
- ST [AN3155: STM32 USART bootloader protocol](https://www.st.com/resource/en/application_note/an3155-usart-protocol-used-in-the-stm32-bootloader-stmicroelectronics.pdf)
- ST [AN2606: STM32 system-memory boot mode](https://www.st.com/resource/en/application_note/an2606-introduction-to-system-memory-boot-mode-on-stm32-mcus-stmicroelectronics.pdf)
