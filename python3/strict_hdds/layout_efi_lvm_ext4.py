#!/usr/bin/python3

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


import functools
from .util import Util, PartiUtil, LvmUtil
from .types import MountCommand
from .handy import EfiMultiDisk, SwapLvmLv, MountEfi, HandyMd, DisksChecker, HandyUtil
from . import errors
from . import StorageLayout


class StorageLayoutImpl(StorageLayout):
    """Layout:
           /dev/sda                 GPT
               /dev/sda1            ESP partition
               /dev/sda2            LVM-PV for VG hdd
           /dev/sdb                 GPT
               /dev/sdb1            reserved ESP partition
               /dev/sdb2            LVM-PV for VG hdd
           /dev/mapper/hdd.root     root device, EXT4
           /dev/mapper/hdd.swap     swap device
       OS:
           1. Linux
       Description:
           1. /dev/sda1 and /dev/sdb1 must has the same size
           2. /dev/sda1 and /dev/sda2 is order-sensitive, no extra partition is allowed
           3. /dev/sdb1 and /dev/sdb2 is order-sensitive, no extra partition is allowed
           4. swap device is optional
           5. extra LVM-LV is allowed to exist
           6. extra harddisk is allowed to exist
    """

    def __init__(self):
        self._md = None              # MultiDisk
        self._swap = None            # SwapLvmLv
        self._mnt = None             # MountEfi

    @property
    def boot_mode(self):
        return StorageLayout.BOOT_MODE_EFI

    @EfiMultiDisk.proxy
    def boot_disk(self):
        pass

    @MountEfi.proxy
    @property
    def mount_point(self):
        pass

    @property
    def dev_rootfs(self):
        return LvmUtil.rootLvDevPath

    @EfiMultiDisk.proxy
    @property
    def dev_boot(self):
        pass

    @SwapLvmLv.proxy
    @property
    def dev_swap(self):
        pass

    def umount_and_dispose(self):
        if True:
            self._mnt.umount()
            del self._mnt
        del self._swap
        del self._md

    @MountEfi.proxy
    def get_mount_comands(self, **kwargs):
        pass

    @MountEfi.proxy
    def is_read_only(self):
        pass

    @MountEfi.proxy
    def get_bootdir_rw_controller(self):
        pass

    def optimize_rootdev(self):
        LvmUtil.autoExtendLv(LvmUtil.rootLvDevPath)
        Util.cmdExec("resize2fs", LvmUtil.rootLvDevPath)

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

    @EfiMultiDisk.proxy
    def get_disk_esp_partition(self, disk):
        pass

    @EfiMultiDisk.proxy
    def get_disk_data_partition(self, disk):
        pass

    @SwapLvmLv.proxy
    def get_swap_size(self):
        pass

    def add_disk(self, disk):
        assert disk is not None

        if disk not in Util.getDevPathListForFixedDisk():
            raise errors.StorageLayoutAddDiskError(disk, errors.NOT_DISK)
        if self._mnt.get_bootdir_rw_controller().is_writable():
            raise errors.StorageLayoutAddDiskError(disk, errors.BOOTDIR_NOT_RO)

        self._md.add_disk(disk, "lvm")

        # create lvm physical volume on partition2 and add it to volume group
        LvmUtil.addPvToVg(self._md.get_disk_data_partition(disk), LvmUtil.vgName)

        assert disk != self._md.boot_disk
        return False

    def remove_disk(self, disk):
        assert disk is not None

        if len(self._md.get_disk_list()) <= 1:
            raise errors.StorageLayoutRemoveDiskError(disk, errors.CAN_NOT_REMOVE_LAST_HDD)
        if self._mnt.get_bootdir_rw_controller().is_writable():
            raise errors.StorageLayoutRemoveDiskError(disk, errors.BOOTDIR_NOT_RO)

        # boot disk change
        if disk == self._md.boot_disk:
            self._mnt.umount_esp(self._md.get_disk_esp_partition(self._md.boot_disk))
            bChange = True
        else:
            bChange = False

        # hdd partition 2: remove from volume group
        parti = self._md.get_disk_data_partition(disk)
        if Util.cmdCallWithRetCode("lvm", "pvmove", parti)[0] != 5:
            raise errors.StorageLayoutRemoveDiskError(disk, "failed")
        Util.cmdCall("lvm", "vgreduce", LvmUtil.vgName, parti)

        # remove
        self._md.remove_disk(disk)

        # boot disk change
        if bChange:
            self._mnt.mount_esp(self._md.get_disk_esp_partition(self._md.boot_disk))
            return True
        else:
            return False

    @SwapLvmLv.proxy
    def create_swap_lv(self):
        pass

    @SwapLvmLv.proxy
    def remove_swap_lv(self):
        pass

    def _check_impl(self, check_item, *kargs, auto_fix=False, error_callback=None):
        if check_item == Util.checkItemBasic:
            with DisksChecker(self._md.get_disk_list()) as dc:
                dc.check_logical_sector_size(auto_fix, error_callback)
                dc.check_boot_sector(auto_fix, error_callback)
                dc.check_partition_type("gpt", auto_fix, error_callback)
                dc.check_partition_uuid(auto_fix, error_callback)
            if True:
                self._md.check_esp(auto_fix, error_callback)
                self._md.check_file_system_uuid(auto_fix, error_callback)
        elif check_item == "swap":
            self._swap.check(auto_fix, error_callback)
        elif check_item == "mount-write-mode":
            self._mnt.check_mount_write_mode(auto_fix, error_callback)
        else:
            assert False


def parse(boot_dev, root_dev, mount_dir):
    if boot_dev is None:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.BOOT_DEV_NOT_EXIST)
    if root_dev != LvmUtil.rootLvDevPath:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.ROOT_DEV_MUST_BE(LvmUtil.rootLvDevPath))
    if Util.getBlkDevFsType(LvmUtil.rootLvDevPath) != Util.fsTypeExt4:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.ROOT_PARTITION_FS_SHOULD_BE(Util.fsTypeExt4))

    # disk_list, boot_disk
    pvDevPathList = HandyUtil.lvmEnsureVgLvAndGetPvList(HandyUtil.getStorageLayoutName(StorageLayoutImpl))
    diskList = [PartiUtil.partiToDisk(x) for x in pvDevPathList]
    bootHdd = HandyMd.checkAndGetBootDiskFromBootDev(HandyUtil.getStorageLayoutName(StorageLayoutImpl), boot_dev, diskList)

    # get mntArgsDict from mount options
    mntArgsDict = dict()
    MountEfi.mntArgsDictSetReadOnly(HandyUtil.getStorageLayoutName(StorageLayoutImpl), mount_dir, mntArgsDict)

    # return
    ret = StorageLayoutImpl()
    ret._md = EfiMultiDisk(diskList=diskList, bootHdd=bootHdd)
    ret._swap = HandyUtil.swapLvDetectAndNew(HandyUtil.getStorageLayoutName(StorageLayoutImpl))
    ret._mnt = MountEfi(True, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)
    return ret


def detect_and_mount(disk_list, mount_dir, mntArgsDict):
    mntArgsDict = mntArgsDict.copy()

    LvmUtil.activateAll()

    # pv list
    pvDevPathList = HandyUtil.lvmEnsureVgLvAndGetPvList(HandyUtil.getStorageLayoutName(StorageLayoutImpl))
    diskList = [PartiUtil.partiToDisk(x) for x in pvDevPathList]
    HandyMd.checkExtraDisks(HandyUtil.getStorageLayoutName(StorageLayoutImpl), pvDevPathList, disk_list)
    bootHdd, bootDev = HandyMd.checkAndGetBootDiskAndBootDev(HandyUtil.getStorageLayoutName(StorageLayoutImpl), diskList)

    # check root lv
    if Util.getBlkDevFsType(LvmUtil.rootLvDevPath) != Util.fsTypeExt4:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.ROOT_PARTITION_FS_SHOULD_BE(Util.fsTypeExt4))

    # return
    ret = StorageLayoutImpl()
    ret._md = EfiMultiDisk(diskList=diskList, bootHdd=bootHdd)
    ret._swap = HandyUtil.swapLvDetectAndNew(HandyUtil.getStorageLayoutName(StorageLayoutImpl))
    ret._mnt = MountEfi(False, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)   # do mount during MountEfi initialization
    return ret


def create_and_mount(disk_list, mount_dir, mntArgsDict):
    mntArgsDict = mntArgsDict.copy()

    # add disks
    md = EfiMultiDisk()
    HandyMd.checkAndAddDisks(disk_list, "lvm")

    # create pv, create vg, create root lv
    for disk in md.get_disk_list():
        LvmUtil.addPvToVg(md.get_disk_data_partition(disk), LvmUtil.vgName)
    LvmUtil.createLvWithDefaultSize(LvmUtil.vgName, LvmUtil.rootLvName)

    # return
    ret = StorageLayoutImpl()
    ret._md = md
    ret._swap = SwapLvmLv(False)
    ret._mnt = MountEfi(False, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)   # do mount during MountEfi initialization
    return ret


def _getMntParams(obj, mntArgsDict):
    tlist = []
    if "extra_mount_options_for_root_dev" in mntArgsDict:
        assert mntArgsDict["extra_mount_options_for_root_dev"] != ""
        tlist += mntArgsDict.pop("extra_mount_options_for_root_dev").split(",")

    tlistBoot = []
    if "extra_mount_options_for_boot_dev" in mntArgsDict:
        assert mntArgsDict["extra_mount_options_for_boot_dev"] != ""
        tlistBoot += mntArgsDict.pop("extra_mount_options_for_boot_dev").split(",")

    ret = [
        MountCommand.Mount(Util.rootfsDir, *Util.rootfsDirModeUidGid, obj.dev_rootfs, Util.fsTypeExt4, mnt_opt_list=tlist),
        MountCommand.Mount(Util.bootDir, *Util.bootDirModeUidGid, obj.dev_boot, Util.fsTypeFat, mnt_opt_list=(Util.bootDirMntOptList + tlistBoot)),
    ]

    MountEfi.mntParamsMergeMntArgReadOnly(ret, mntArgsDict)

    return ret
