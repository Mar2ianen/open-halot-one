# System snapshot

## Scope

The local snapshot is a read-only capture of the HALOT-ONE eMMC user area plus the separate eMMC boot0/boot1 areas. It includes the device's installed firmware, configuration, logs, keys, Wi-Fi credentials, and files on `/mnt/UDISK`; treat it as private. It is not uploaded to this public repository.

RPMB is not part of the user-area image and was not read. The image is taken while Linux is running, so writable ext4 filesystems may not be crash-consistent. Keep the original image unchanged and work on copies when extracting or modifying firmware.

## On-device layout observed

The kernel command line describes GPT entries `bootloader`, `env`, `env-redund`, `recovery`, `boot`, `rootfs`, `rootfs_data`, `misc`, `private`, and `UDISK` on `/dev/mmcblk0p1` through `p10`. At runtime, `p6` is read-only SquashFS `/rom`; `p7` is ext4 `/overlay`; `p9` is VFAT `/device`; and `p10` is ext4 `/mnt/UDISK`.

The live `/proc/partitions` output reports `/dev/mmcblk0` as 7,636,800 KiB with ten GPT partitions, plus separate 4 MiB `boot0` and `boot1` hardware areas and a 4 MiB RPMB device. Linux reports `boot0` and `boot1` read-only (`ro=1`); both captured areas contain only zero bytes. `/proc/mtd` is absent, so the boot storage here is eMMC rather than an exposed raw-NAND/MTD layout.

Comparing the vendor TOC1 update member with the complete user-area capture found the entire 1,294,336-byte U-Boot package at byte offset `0x01004000` (sector 32,800), ending at `0x0113c000`. This is in the reserved user-area gap before `p1` starts at sector 73,728 (`0x02400000`), not in the hardware `boot0`/`boot1` areas or the FAT16 `p1`. Static reversal of the installed SWUpdate handler resolves the write route for the live `boot_type=2`, `sunxi_secure: normal` configuration: clear 1 MiB at byte offset `0x012a6000`, then write the full package at sector `0x8020` (`0x01004000`) and sync it. The cleared region is zero-filled in the snapshot; its role is unknown. The package SHA-256 is `75b7f37ad259842c72c505b4ec2289a426b819004298799c4b15bbf24a7544c4`; its embedded version matches the running U-Boot. Allwinner BOOT0/SPL strings occur at offsets `0x0000c635` and `0x0000c65c` in the user-area prefix, but the exact first-stage image boundaries and ROM selection rules remain unknown. No writes were made during analysis.

Read-only `fw_printenv` confirmed U-Boot `bootdelay=0`, `boot_partition=boot`, and `bootcmd=run setargs_nand boot_normal`. `boot_normal` reads the selected `boot` partition into RAM at `0x45000000` and invokes `bootm`; the running kernel confirms its root at `/dev/mmcblk0p6`. The redundant environment utility config points to `env` and `env-redund`, each with a 128 KiB environment region. No environment variables or partitions were changed.

The whole user-area block device reports 7,636,800 KiB (7,820,083,200 bytes). The read-only capture completed at that exact byte count. The local zstd image decodes to the same SHA-256 as the captured raw stream. Separate 4 MiB `boot0` and `boot1` captures also completed; their hashes match each other. Exact file sizes and checksums are in the local `snapshot/manifest.txt`.

## Private local artifact set

The owner-facing outputs directory contains the compressed complete image, boot0/boot1 captures, per-artifact hashes, a manifest, the original `PrinterUI` clone, and focused decompilation outputs. It is intentionally excluded from Git. Device serials, MAC addresses, IP addresses, credentials, SSH keys, and print-file names are omitted from this public page.

## Reproduction tools

- ADB through the rear USB device/debug port (`Allwinner` / `Tina` USB gadget).
- `adb pull /dev/mmcblk0` for the eMMC user area.
- `adb pull /dev/mmcblk0boot0` and `adb pull /dev/mmcblk0boot1` for the eMMC boot areas.
- `sha256sum` to identify each capture; `zstd` is used only on the host to compress the completed image.
