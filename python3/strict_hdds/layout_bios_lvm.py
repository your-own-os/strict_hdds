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


import os
import re

from . import util
from .util import LvmUtil

from . import errors
from . import StorageLayout


class StorageLayoutImpl(StorageLayout):
    """Layout:
           /dev/sda                 MBR, BIOS-GRUB
               /dev/sda1            LVM-PV for VG hdd
           /dev/mapper/hdd.root     root device, EXT4
           /dev/mapper/hdd.swap     swap device
       Description:
           1. only one partition is allowed in LVM-PV device
           2. swap device is optional
           3. extra LVM-LV is allowed to exist
           4. extra harddisk is allowed to exist
    """

    @property
    def name(self):
        return util.modName2layoutName(self.__module__.__name__)

    def __init__(self):
        self._diskList = []         # harddisk list
        self._bSwapLv = None        # whether swap lv exists
        self._bootHdd = None        # boot harddisk name

    @property
    def boot_mode(self):
        return StorageLayout.BOOT_MODE_BIOS

    @property
    def dev_rootfs(self):
        return LvmUtil.rootLvDevPath

    @property
    def dev_swap(self):
        return LvmUtil.swapLvDevPath if self._bSwapLv else None

    def get_boot_disk(self):
        return self._bootHdd

    def check_swap_size(self):
        assert self._bSwapLv
        return util.getBlkDevSize(LvmUtil.swapLvDevPath) >= util.getSwapSize()

    def optimize_rootdev(self):
        util.autoExtendLv(LvmUtil.rootLvDevPath)

    def get_disk_list(self):
        return self._diskList

    def add_disk(self, devpath):
        assert devpath is not None
        assert devpath not in self._diskList

        if devpath not in util.getDevPathListForFixedHdd():
            raise errors.StorageLayoutAddDiskError(devpath, errors.NOT_DISK)

        # FIXME
        assert False

    def release_disk(self, devpath):
        assert devpath is not None
        assert devpath in self._diskList
        assert len(self._diskList) > 1

        parti = util.devPathDiskToPartition(devpath, 1)
        rc, out = util.cmdCallWithRetCode("/sbin/lvm", "pvmove", parti)
        if rc != 5:
            raise errors.StorageLayoutReleaseDiskError(devpath, "failed")

    def remove_disk(self, devpath):
        assert devpath is not None
        assert devpath in self._diskList
        assert len(self._diskList) > 1

        # change boot device if needed
        ret = False
        if self._bootHdd == devpath:
            self._diskList.remove(devpath)
            self._bootHdd = self._diskList[0]
            # FIXME: add Boot Code for self._bootHdd?
            ret = True

        # remove harddisk
        parti = util.devPathDiskToPartition(devpath, 1)
        util.cmdCall("/sbin/lvm", "vgreduce", LvmUtil.vgName, parti)
        util.wipeHarddisk(devpath)

        return ret

    def create_swap_lv(self):
        assert not self._bSwapLv
        util.cmdCall("/sbin/lvm", "lvcreate", "-L", "%dGiB" % (util.getSwapSizeInGb()), "-n", LvmUtil.swapLvName, LvmUtil.vgName)
        self._bSwapLv = True

    def remove_swap_lv(self):
        assert self._bSwapLv
        util.cmdCall("/sbin/lvm", "lvremove", LvmUtil.swapLvDevPath)
        self._bSwapLv = False


def create_layout(disk_list=None, dry_run=False):
    if disk_list is None:
        disk_list = util.getDevPathListForFixedHdd()
        if len(disk_list) == 0:
            raise errors.StorageLayoutCreateError(errors.NO_DISK)
    else:
        assert len(disk_list) > 0

    if not dry_run:
        for devpath in disk_list:
            # create partitions
            util.initializeDisk(devpath, "mbr", [
                ("*", "lvm"),
            ])

            # create lvm physical volume on partition1 and add it to volume group
            parti = util.devPathDiskToPartition(devpath, 1)
            util.cmdCall("/sbin/lvm", "pvcreate", parti)
            if not util.cmdCallTestSuccess("/sbin/lvm", "vgdisplay", LvmUtil.vgName):
                util.cmdCall("/sbin/lvm", "vgcreate", LvmUtil.vgName, parti)
            else:
                util.cmdCall("/sbin/lvm", "vgextend", LvmUtil.vgName, parti)

        # create root lv
        out = util.cmdCall("/sbin/lvm", "vgdisplay", "-c", LvmUtil.vgName)
        freePe = int(out.split(":")[15])
        util.cmdCall("/sbin/lvm", "lvcreate", "-l", "%d" % (freePe // 2), "-n", LvmUtil.rootLvName, LvmUtil.vgName)

    # return value
    ret = StorageLayoutImpl()
    ret._diskList = disk_list
    ret._bSwapLv = False
    ret._bootHdd = ret._diskList[0]     # FIXME
    return ret


def parse_layout(booDev, rootDev):
    ret = StorageLayoutImpl()

    # vg
    if not util.cmdCallTestSuccess("/sbin/lvm", "vgdisplay", LvmUtil.vgName):
        raise errors.StorageLayoutParseError(ret.name, errors.LVM_VG_NOT_FOUND(LvmUtil.vgName))

    # pv list
    out = util.cmdCall("/sbin/lvm", "pvdisplay", "-c")
    for m in re.finditer("(/dev/\\S+):%s:.*" % (LvmUtil.vgName), out, re.M):
        hdd = util.devPathPartitionToDisk(m.group(1))
        if util.getBlkDevPartitionTableType(hdd) != "dos":
            raise errors.StorageLayoutParseError(ret.name, errors.PART_TYPE_SHOULD_BE(hdd, "dos"))
        if os.path.exists(util.devPathDiskToPartition(hdd, 2)):
            raise errors.StorageLayoutParseError(ret.name, errors.DISK_HAS_REDUNDANT_PARTITION(hdd))
        ret._diskList.append(hdd)

    out = util.cmdCall("/sbin/lvm", "lvdisplay", "-c")

    # root lv
    if re.search("/dev/hdd/root:%s:.*" % (LvmUtil.vgName), out, re.M) is not None:
        fs = util.getBlkDevFsType(LvmUtil.rootLvDevPath)
        if fs != util.fsTypeExt4:
            raise errors.StorageLayoutParseError(ret.name, "root partition file system is \"%s\", not \"ext4\"" % (fs))
    else:
        raise errors.StorageLayoutParseError(ret.name, errors.LVM_LV_NOT_FOUND(LvmUtil.rootLvDevPath))

    # swap lv
    if re.search("/dev/hdd/swap:%s:.*" % (LvmUtil.vgName), out, re.M) is not None:
        if util.getBlkDevFsType(LvmUtil.swapLvDevPath) != util.fsTypeSwap:
            raise errors.StorageLayoutParseError(ret.name, errors.SWAP_DEV_HAS_INVALID_FS_FLAG(LvmUtil.swapLvDevPath))
        ret._bSwapLv = True

    # boot harddisk
    for hdd in ret._diskList:
        with open(hdd, "rb") as f:
            if not util.isBufferAllZero(f.read(440)):
                if ret._bootHdd is not None:
                    raise errors.StorageLayoutParseError(ret.name, errors.BOOT_CODE_ON_MULTIPLE_DISKS)
                ret._bootHdd = hdd
    if ret._bootHdd is None:
        raise errors.StorageLayoutParseError(ret.name, errors.BOOT_CODE_NOT_FOUND)

    return ret
