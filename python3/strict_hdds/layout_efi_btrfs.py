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
from .util import Util, PartiUtil, BtrfsUtil
from .handy import EfiMultiDisk, SubVols, SubVolsBtrfs, MountEfi, MountParam, HandyMd, DisksChecker
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
       OS:
           1. Linux
       Description:
           1. /dev/sda1 and /dev/sdb1 must has the same size
           2. /dev/sda1 and /dev/sda2 is order-sensitive, no extra partition is allowed
           3. /dev/sdb1 and /dev/sdb2 is order-sensitive, no extra partition is allowed
           4. use optional swap file /var/swap/swap.dat, at this time /var/swap is a standalone sub-volume
           5. extra harddisk is allowed to exist
    """

    def __init__(self):
        self._md = None              # MultiDisk
        self._subvols = None         # SubVolsBtrfs
        self._mnt = None             # MountEfi

    @property
    def boot_mode(self):
        return StorageLayout.BOOT_MODE_EFI

    @property
    def dev_rootfs(self):
        return self.get_disk_data_partition(self.get_disk_list()[0])

    @EfiMultiDisk.proxy
    @property
    def dev_boot(self):
        pass

    @EfiMultiDisk.proxy
    def boot_disk(self):
        pass

    @SubVols.proxy
    @property
    def snapshot(self):
        pass

    @MountEfi.proxy
    @property
    def mount_point(self):
        pass

    def umount_and_dispose(self):
        if True:
            self._mnt.umount()
            del self._mnt
        del self._md

    @MountEfi.proxy
    def get_mount_params(self, **kwargs):
        pass

    @MountEfi.proxy
    def get_mount_entries(self):
        pass

    @MountEfi.proxy
    def is_read_only(self):
        pass

    @MountEfi.proxy
    def get_bootdir_rw_controller(self):
        pass

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

    @SubVols.proxy
    def get_snapshot_list(self):
        pass

    def add_disk(self, disk):
        assert disk is not None

        if disk not in Util.getDevPathListForFixedDisk():
            raise errors.StorageLayoutAddDiskError(disk, errors.NOT_DISK)
        if self._mnt.get_bootdir_rw_controller().is_writable():
            raise errors.StorageLayoutAddDiskError(disk, errors.BOOTDIR_NOT_RO)

        self._md.add_disk(disk, Util.fsTypeBtrfs)

        # hdd partition 2: make it as backing device and add it to btrfs filesystem
        BtrfsUtil.addDiskToBtrfs(self._md.get_disk_data_partition(disk), self._mnt.mount_point)

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

        # hdd partition 2: remove from btrfs and bcache
        Util.cmdCall("btrfs", "device", "delete", self._md.get_disk_data_partition(disk), self._mnt.mount_point)

        # remove
        self._md.remove_disk(disk)

        # boot disk change
        if bChange:
            self._mnt.mount_esp(self._md.get_disk_esp_partition(self._md.boot_disk))
            return True
        else:
            return False

    @SubVols.proxy
    def create_snapshot(self, snapshot_name):
        pass

    @SubVols.proxy
    def remove_snapshot(self, snapshot_name):
        pass

    @SubVols.proxy
    def sync_from_snapshot(self, snapshot_name, home=False, var=False):
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
            self._subvols.check(auto_fix, error_callback)
        elif check_item == "mount-write-mode":
            self._mnt.check_mount_write_mode(auto_fix, error_callback)
        else:
            assert False


def parse(boot_dev, root_dev, mount_dir):
    if boot_dev is None:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.BOOT_DEV_NOT_EXIST)
    if Util.getBlkDevFsType(root_dev) != Util.fsTypeBtrfs:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.ROOT_PARTITION_FS_SHOULD_BE(Util.fsTypeBtrfs))

    # disk_list, boot_disk
    partiList = BtrfsUtil.getSlaveDevPathList(mount_dir)
    diskList = [PartiUtil.partiToDisk(x) for x in partiList]
    bootHdd = HandyMd.checkAndGetBootDiskFromBootDev(HandyUtil.getStorageLayoutName(StorageLayoutImpl), boot_dev, diskList)

    # get mntArgsDict from mount options
    mntArgsDict = dict()
    SubVolsBtrfs.mntArgsDictSetSnapshot(HandyUtil.getStorageLayoutName(StorageLayoutImpl), mount_dir, mntArgsDict)
    MountEfi.mntArgsDictSetReadOnly(HandyUtil.getStorageLayoutName(StorageLayoutImpl), mount_dir, mntArgsDict)

    # return
    ret = StorageLayoutImpl()
    ret._md = EfiMultiDisk(diskList=diskList, bootHdd=bootHdd)
    ret._subvols = SubVolsBtrfs(mount_dir, snapshot=mntArgsDict.get("snapshot", None))
    ret._mnt = MountEfi(True, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)
    return ret


def detect_and_mount(disk_list, mount_dir, mntArgsDict):
    mntArgsDict = mntArgsDict.copy()

    # filter
    diskList = []
    for d in disk_list:
        i = 1
        while True:
            parti = PartiUtil.diskToParti(d, i)
            if not PartiUtil.partiExists(parti):
                break
            if Util.getBlkDevFsType(parti) == Util.fsTypeBtrfs:
                diskList.append(d)
                break
            i += 1
    if len(diskList) == 0:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.DISK_NOT_FOUND)

    # bootDisk & bootDev
    bootHdd = HandyMd.checkAndGetBootDiskAndBootDev(HandyUtil.getStorageLayoutName(StorageLayoutImpl), diskList)[0]

    # return
    ret = StorageLayoutImpl()
    ret._md = EfiMultiDisk(diskList=diskList, bootHdd=bootHdd)
    ret._subvols = SubVolsBtrfs(mount_dir, snapshot=mntArgsDict.get("snapshot", None))
    ret._mnt = MountEfi(False, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)       # do mount during MountEfi initialization
    return ret


def create_and_mount(disk_list, mount_dir, mntArgsDict):
    mntArgsDict = mntArgsDict.copy()

    # add disks
    md = EfiMultiDisk()
    HandyMd.checkAndAddDisks(disk_list, Util.fsTypeBtrfs)

    # create and mount
    partiList = [md.get_disk_data_partition(x) for x in md.get_disk_list()]
    Util.cmdCall("mkfs.btrfs", "-f", "-d", "single", "-m", "single", *partiList)
    SubVolsBtrfs.initializeFs(partiList[0], ["device=%s" % (x) for x in partiList])

    # return
    ret = StorageLayoutImpl()
    ret._md = md
    ret._subvols = SubVolsBtrfs(mount_dir, snapshot=mntArgsDict.get("snapshot", None))
    ret._mnt = MountEfi(False, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)       # do mount during MountEfi initialization
    return ret


def _getMntParams(obj, mntArgsDict):
    tlist = ["device=%s" % (obj._md.get_disk_data_partition(x)) for x in obj._md.get_disk_list()]
    if "extra_mount_options_for_root_dev" in mntArgsDict:
        assert mntArgsDict["extra_mount_options_for_root_dev"] != ""
        tlist += mntArgsDict.pop("extra_mount_options_for_root_dev").split(",")

    tlistBoot = []
    if "extra_mount_options_for_boot_dev" in mntArgsDict:
        assert mntArgsDict["extra_mount_options_for_boot_dev"] != ""
        tlistBoot += mntArgsDict.pop("extra_mount_options_for_boot_dev").split(",")

    ret = []
    for dirPath, dirMode, dirUid, dirGid, mntOptList in SubVolsBtrfs.getParamsForMountWithoutSnapshot():
        ret.append(MountParam(dirPath, dirMode, dirUid, dirGid, obj.dev_rootfs, Util.fsTypeBtrfs, mnt_opt_list=(mntOptList + tlist)))
    ret.append(MountParam(Util.bootDir, *Util.bootDirModeUidGid, obj.dev_boot, Util.fsTypeFat, mnt_opt_list=(Util.bootDirMntOptList + tlistBoot)))

    SubVolsBtrfs.mntParamsMergeMntArgSnapshot(ret, mntArgsDict)
    MountEfi.mntParamsMergeMntArgReadOnly(ret, mntArgsDict)

    return ret
