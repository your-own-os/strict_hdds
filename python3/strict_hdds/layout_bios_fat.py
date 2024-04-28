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
from .util import Util, PartiUtil, MbrUtil
from .handy import MountBios, MountParam, DisksChecker, HandyUtil
from . import errors
from . import StorageLayout


class StorageLayoutImpl(StorageLayout):
    """Layout:
           /dev/sda          stores MBR
               /dev/sda1     windows partition, FAT32
       OS:
           1. Microsoft Windows 95
           2. Microsoft Windows 98
       Description:
           1. partition number of /dev/sda1 and /dev/sda2 is irrelevant
           2. extra partition is allowed to exist
    """

    def __init__(self):
        self._hdd = None              # boot harddisk name
        self._hddRootParti = False    # root partition name
        self._mnt = None              # MountBios

    @property
    def boot_mode(self):
        return StorageLayout.BOOT_MODE_BIOS

    @property
    def dev_rootfs(self):
        return self._hddRootParti

    @property
    def dev_boot(self):
        assert False

    @property
    def boot_disk(self):
        return self._hdd

    @MountBios.proxy
    @property
    def mount_point(self):
        pass

    def umount_and_dispose(self):
        if True:
            self._mnt.umount()
            del self._mnt
        del self._hddRootParti
        del self._hdd

    @MountBios.proxy
    def get_mount_params(self, **kwargs):
        pass

    @MountBios.proxy
    def get_mount_entries(self):
        pass

    @MountBios.proxy
    def is_read_only(self):
        pass

    def get_disk_list(self):
        return [self._hdd]

    def _check_impl(self, check_item, *kargs, auto_fix=False, error_callback=None):
        if check_item == Util.checkItemBasic:
            with DisksChecker([self._hdd]) as dc:
                dc.check_logical_sector_size(auto_fix, error_callback)
                dc.check_boot_sector(auto_fix, error_callback)
                dc.check_partition_type("msdos", auto_fix, error_callback)
        elif check_item == "mount-write-mode":
            self._mnt.check_mount_write_mode(auto_fix, error_callback)
        else:
            assert False


def parse(boot_dev, root_dev, mount_dir):
    if boot_dev is not None:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.BOOT_DEV_SHOULD_NOT_EXIST)
    if Util.getBlkDevFsType(root_dev) != Util.fsTypeFat:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.ROOT_PARTITION_FS_SHOULD_BE(Util.fsTypeExt4))

    # hdd
    hdd = PartiUtil.partiToDisk(root_dev)
    if Util.getBlkDevPartitionTableType(hdd) != Util.diskPartTableMbr:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.PARTITION_TYPE_SHOULD_BE(hdd, Util.diskPartTableMbr))

    # get mntArgsDict from mount options
    mntArgsDict = dict()
    MountBios.mntArgsDictSetReadOnly(HandyUtil.getStorageLayoutName(StorageLayoutImpl), mount_dir, mntArgsDict)

    # return
    ret = StorageLayoutImpl()
    ret._hdd = hdd
    ret._hddRootParti = root_dev
    ret._mnt = MountBios(True, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)
    return ret


def detect_and_mount(disk_list, mount_dir, mntArgsDict):
    mntArgsDict = mntArgsDict.copy()

    # scan for root partition
    rootPartitionList = []
    for disk in disk_list:
        if not MbrUtil.hasBootCode(disk):                                           # no boot code, ignore unbootable disk
            continue
        if Util.getBlkDevPartitionTableType(disk) != Util.diskPartTableMbr:         # only accept disk with MBR partition table
            continue
        i = 1
        while True:
            parti = PartiUtil.diskToParti(disk, i)
            if not PartiUtil.partiExists(parti):
                break
            if Util.getBlkDevFsType(parti) == Util.fsTypeFat:
                rootPartitionList.append(parti)
            i += 1
    if len(rootPartitionList) == 0:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.ROOT_PARTITION_NOT_FOUND)
    if len(rootPartitionList) > 1:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.ROOT_PARTITIONS_TOO_MANY)

    # return
    ret = StorageLayoutImpl()
    ret._hdd = PartiUtil.partiToDisk(rootPartitionList[0])
    ret._hddRootParti = rootPartitionList[0]
    ret._mnt = MountBios(False, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)      # do mount during MountBios initialization
    return ret


def create_and_mount(disk_list, mount_dir, mntArgsDict):
    mntArgsDict = mntArgsDict.copy()

    # create partitions
    hdd = HandyUtil.checkAndGetHdd(disk_list)
    Util.initializeDisk(hdd, Util.diskPartTableMbr, [
        ("*", Util.fsTypeFat),
    ])

    # root partition
    rootParti = PartiUtil.diskToParti(hdd, 1)

    # return
    ret = StorageLayoutImpl(mount_dir)
    ret._hdd = hdd
    ret._hddRootParti = rootParti
    ret._mnt = MountBios(False, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)      # do mount during MountBios initialization
    return ret


def _getMntParams(obj, mntArgsDict):
    tlist = []
    if "extra_mount_options" in mntArgsDict:
        assert "extra_mount_options_for_root_dev" not in mntArgsDict
        assert mntArgsDict["extra_mount_options"] != ""
        tlist += mntArgsDict.pop("extra_mount_options").split(",")
    if "extra_mount_options_for_root_dev" in mntArgsDict:
        assert "extra_mount_options" not in mntArgsDict
        assert mntArgsDict["extra_mount_options_for_root_dev"] != ""
        tlist += mntArgsDict.pop("extra_mount_options_for_root_dev").split(",")
    mntParams = [
        MountParam(Util.rootfsDir, *Util.rootfsDirModeUidGid, obj.dev_rootfs, Util.fsTypeFat, mnt_opt_list=tlist)
    ]
    MountBios.mntParamsMergeMntArgReadOnly(mntParams, mntArgsDict)
    return mntParams
