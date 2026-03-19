# strict_hdds

Ensures only some optimized harddisk layouts are used.

## Description

strict_hdds is a Python library that provides a standardized approach to managing hard disk layouts on Linux systems.

Storage layouts properties:
- **Single Filesystem**: A single filesystem is exposed to user if multiple disks are used. Use simple linear layout, RAID is not supported.
- **SSD caching**: SSD caching is supported if possible.
- **OS Compatibility**: Storage layout are for various operating systems. Note strict_hdds itself can only be used on Linux systems.
- **Swap Support**: Swap is supported in all layouts. Swap file is prefered.

## Supported Storage Layouts

### BIOS Boot Layouts
- `bios-ext4` - BIOS boot with ext4 filesystem
- `bios-fat` - BIOS boot with FAT filesystem
- `bios-ntfs` - BIOS boot with NTFS filesystem

### EFI Boot Layouts
- `efi-ext4` - EFI boot with ext4 filesystem
- `efi-xfs` - EFI boot with XFS filesystem
- `efi-btrfs` - EFI boot with Btrfs filesystem
- `efi-bcache-btrfs` - EFI boot with Btrfs and bcache support
- `efi-bcachefs` - EFI boot with bcachefs filesystem
- `efi-msr-ntfs` - EFI boot with Microsoft Reserved partition and NTFS

## Usage

### Python API

```python
import strict_hdds

# Show supported layout names
layouts = strict_hdds.get_supported_storage_layout_names()
print(layouts)

# Get storage layout for a mounted directory
layout = strict_hdds.get_storage_layout("/mnt")

# Mount a storage layout
layout = strict_hdds.mount_storage_layout(
    "/mnt",
    layout_name="efi-ext4")

# Create and mount a new storage layout
layout = strict_hdds.create_and_mount_storage_layout(
    "efi-ext4",
    "/mnt",
    disk_list=["/dev/sda"],
    read_only=False
)

# Check the layout
layout.check(auto_fix=True)

# Get mount commands
commands = layout.get_mount_commands()

# Unmount
layout.umount_and_dispose()
```

## License

This project is licensed under the GPLv3 License. See the LICENSE file for details.

## Author

Fpemud <fpemud@sina.com>

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Links

- Gitee: https://gitee.com/your-own-os/strict_hdds
- GitHub: https://github.com/your-own-os/strict_hdds
