#!/usr/bin/env python3

# Copyright (c) 2020-2021 Fpemud <fpemud@sina.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.


from .util import Util, GptUtil, EfiMultiDisk

from . import errors
from . import StorageLayout


class StorageLayoutImpl(StorageLayout):
    """Layout:
           /dev/sda                 GPT
               /dev/sda1            ESP partition
               /dev/sda2            btrfs device
           /dev/sdb                 GPT
               /dev/sdb1            reserved ESP partition
               /dev/sdb2            btrfs device
           /dev/sda1:/dev/sda2      root device, btrfs
       Description:
           1. /dev/sda1 and /dev/sdb1 must has the same size
           2. /dev/sda1 and /dev/sda2 is order-sensitive, no extra partition is allowed
           3. /dev/sdb1 and /dev/sdb2 is order-sensitive, no extra partition is allowed
           4. use optional swap file /var/swap/swap.dat, at this time /var/swap is a standalone sub-volume
           5. extra harddisk is allowed to exist
    """

    def __init__(self, mount_dir):
        super().__init__(mount_dir)
        self._md = None                         # MultiDisk

    @property
    def boot_mode(self):
        return StorageLayout.BOOT_MODE_EFI

    @property
    def dev_rootfs(self):
        return self._md.get_disk_list()[0]

    @property
    def dev_boot(self):
        raise self._md.get_esp()

    @property
    def dev_swap(self):
        assert False

    @EfiMultiDisk.proxy
    def boot_disk(self):
        pass

    def check(self):
        assert False

    @EfiMultiDisk.proxy
    def get_esp(self):
        pass

    @EfiMultiDisk.proxy
    def get_pending_esp_list(self):
        pass

    @EfiMultiDisk.proxy
    def sync_esp(self, dst):
        pass

    @EfiMultiDisk.proxy
    def get_disk_list(self):
        pass

    def add_disk(self, disk):
        assert disk is not None

        if disk not in Util.getDevPathListForFixedDisk():
            raise errors.StorageLayoutAddDiskError(disk, errors.NOT_DISK)

        lastBootDisk = self._md.boot_disk

        # add
        self._md.add_disk(disk)

        # hdd partition 2: make it as backing device and add it to btrfs filesystem
        Util.cmdCall("/sbin/btrfs", "device", "add", self._md.get_disk_data_partition(disk), "/")

        return lastBootDisk != self._md.boot_disk     # boot disk may change

    def remove_disk(self, disk):
        assert disk is not None
        assert disk in self._md.get_disk_list()

        if len(self._md.get_disk_list()) <= 1:
            raise errors.StorageLayoutRemoveDiskError(errors.CAN_NOT_REMOVE_LAST_HDD)

        lastBootHdd = self._md.boot_disk

        # hdd partition 2: remove from btrfs and bcache
        Util.cmdCall("/sbin/btrfs", "device", "delete", self._md.get_disk_data_partition(disk), "/")

        # remove
        self._md.remove_disk(disk)

        return lastBootHdd != self._md.boot_disk     # boot disk may change


def create_and_mount(disk_list=None):
    if disk_list is None:
        disk_list = Util.getDevPathListForFixedDisk()
        if len(disk_list) == 0:
            raise errors.StorageLayoutCreateError(errors.NO_DISK_WHEN_CREATE)
    else:
        assert len(disk_list) > 0

    ret = StorageLayoutImpl()

    ret._md = EfiMultiDisk()
    for devpath in disk_list:
        ret._md.add_disk(devpath)

    return ret


def parse(bootDev, rootDev):
    ret = StorageLayoutImpl()

    if not GptUtil.isEspPartition(bootDev):
        raise errors.StorageLayoutParseError(ret.name, errors.BOOT_DEV_IS_NOT_ESP)

    # boot harddisk
    ret._md = EfiMultiDisk()
    ret._md = Util.devPathPartiToDisk(bootDev)

    return ret