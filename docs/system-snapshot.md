# System snapshot

## Scope

The local snapshot is a read-only capture of the HALOT-ONE eMMC user area plus the separate eMMC boot0/boot1 areas. It includes the device's installed firmware, configuration, logs, keys, Wi-Fi credentials, and files on `/mnt/UDISK`; treat it as private. It is not uploaded to this public repository.

RPMB is not part of the user-area image and was not read. The image is taken while Linux is running, so writable ext4 filesystems may not be crash-consistent. Keep the original image unchanged and work on copies when extracting or modifying firmware.

## On-device layout observed

The kernel command line describes GPT entries `bootloader`, `env`, `env-redund`, `recovery`, `boot`, `rootfs`, `rootfs_data`, `misc`, `private`, and `UDISK` on `/dev/mmcblk0p1` through `p10`. At runtime, `p6` is read-only SquashFS `/rom`; `p7` is ext4 `/overlay`; `p9` is VFAT `/device`; and `p10` is ext4 `/mnt/UDISK`.

The whole user-area block device reports 7,636,800 KiB. Exact partition start/size values and image checksums are recorded in the local `snapshot/manifest.txt` after capture completes.

## Private local artifact set

The owner-facing outputs directory contains the compressed complete image, boot0/boot1 captures, per-artifact hashes, a manifest, the original `PrinterUI` clone, and focused decompilation outputs. It is intentionally excluded from Git. Device serials, MAC addresses, IP addresses, credentials, SSH keys, and print-file names are omitted from this public page.

## Reproduction tools

- ADB through the rear USB device/debug port (`Allwinner` / `Tina` USB gadget).
- `adb pull /dev/mmcblk0` for the eMMC user area.
- `adb pull /dev/mmcblk0boot0` and `adb pull /dev/mmcblk0boot1` for the eMMC boot areas.
- `sha256sum` to identify each capture; `zstd` is used only on the host to compress the completed image.
