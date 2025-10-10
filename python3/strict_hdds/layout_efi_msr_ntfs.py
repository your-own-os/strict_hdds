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
import subprocess
from .util import Util, PartiUtil, GptUtil, WinUtil, InitDisk
from .types import BootMode, MountCommand
from .handy import MountEfi, DisksChecker, HandyUtil
from . import errors
from . import StorageLayout


class StorageLayoutImpl(StorageLayout):
    """Layout:
           /dev/sda          GPT
               /dev/sda1     ESP partition
               /dev/sda2     MSR partition
               /dev/sda3     windows system partition, NTFS
       OS:
           1. Microsoft Windows 7
           2. Microsoft Windows 10
           3. Microsoft Windows 11
           4. Microsoft Windows Server 2003
           5. Microsoft Windows Server 2010
       Description:
           1. the 3 partitions in /dev/sda is order-sensitive
           2. extra partition is allowed to exist
    """

    def __init__(self):
        self._hdd = None                 # boot harddisk name
        self._hddEspParti = None         # ESP partition name
        self._hddMsrParti = None         # MSR partition name
        self._hddSysParti = None         # windows system partition name
        self._mnt = None                 # MountEfi

    @property
    def boot_mode(self):
        return BootMode.EFI

    @property
    def boot_disk(self):
        return self._hdd

    @MountEfi.proxy
    @property
    def mount_point(self):
        pass

    @property
    def dev_esp(self):
        return self._hddEspParti

    @property
    def dev_msr(self):
        return self._hddMsrParti

    @property
    def dev_sys(self):
        return self._hddSysParti

    def umount_and_dispose(self):
        if True:
            self._mnt.umount()
            del self._mnt
        del self._hddSysParti
        del self._hddEspParti
        del self._hdd

    @MountEfi.proxy
    def get_mount_commands(self, **kwargs):
        pass

    @MountEfi.proxy
    def is_read_only(self):
        pass

    @MountEfi.proxy
    def get_bootdir_rw_controller(self):
        pass

    def get_esp(self):
        return self._hddEspParti

    def get_disk_list(self):
        return [self._hdd]

    def _check_impl(self, check_item, *kargs, auto_fix=False, error_callback=None):
        if check_item == Util.checkItemBasic:
            with DisksChecker([self._hdd]) as dc:
                dc.check_logical_sector_size(auto_fix, error_callback)
                dc.check_boot_sector(auto_fix, error_callback)
                dc.check_partition_type("gpt", auto_fix, error_callback)
                dc.check_partition_uuid(auto_fix, error_callback)
        elif check_item == "mount-write-mode":
            self._mnt.check_mount_write_mode(auto_fix, error_callback)
        else:
            assert False


def parse(boot_dev, root_dev, mount_dir):
    disk, espPartId = PartiUtil.partiToDiskAndPartiId(boot_dev)
    disk2, sysPartId = PartiUtil.partiToDiskAndPartiId(root_dev)
    if disk != disk2:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), "boot device and root device are not on the same harddisk")
    if espPartId + 2 != sysPartId:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), "MSR partition not found")
    if not GptUtil.isEspPartition(boot_dev):
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.BOOT_DEV_IS_NOT_ESP)
    if Util.getBlkDevFsType(root_dev) != "ntfs":
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.SYS_PARTITION_FS_SHOULD_BE("ntfs"))

    # get mntArgsDict from mount options
    mntArgsDict = dict()
    MountEfi.mntArgsDictSetReadOnly(HandyUtil.getStorageLayoutName(StorageLayoutImpl), mount_dir, mntArgsDict)

    # return
    ret = StorageLayoutImpl()
    ret._hdd = PartiUtil.partiToDisk(boot_dev)
    ret._hddEspParti = boot_dev
    ret._hddMsrParti = PartiUtil.diskToParti(disk, espPartId + 1)
    ret._hddSysParti = root_dev
    ret._mnt = MountEfi(True, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)
    return ret


def detect_and_mount(disk_list, mount_dir, mntArgsDict):
    mntArgsDict = mntArgsDict.copy()

    # scan for ESP, MSR and system partition
    espAndMsrAndSysPartitionList = []
    for disk in disk_list:
        espParti = PartiUtil.diskToParti(disk, 1)
        msrParti = PartiUtil.diskToParti(disk, 2)
        sysParti = PartiUtil.diskToParti(disk, 3)
        if not PartiUtil.partiExists(espParti):
            continue
        if not PartiUtil.partiExists(msrParti):
            continue
        if not PartiUtil.partiExists(sysParti):
            continue
        if not GptUtil.isEspPartition(espParti):
            continue
        if Util.getBlkDevFsType(sysParti) != "ntfs":
            continue
        espAndMsrAndSysPartitionList.append((disk, espParti, msrParti, sysParti))
    if len(espAndMsrAndSysPartitionList) == 0:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.DISK_NOT_FOUND)
    if len(espAndMsrAndSysPartitionList) > 1:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.DISK_TOO_MANY)

    # return
    ret = StorageLayoutImpl()
    ret._hdd = espAndMsrAndSysPartitionList[0][0]
    ret._hddEspParti = espAndMsrAndSysPartitionList[0][1]
    ret._hddMsrParti = espAndMsrAndSysPartitionList[0][2]
    ret._hddSysParti = espAndMsrAndSysPartitionList[0][3]
    ret._mnt = MountEfi(False, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)             # do mount during MountEfi initialization
    return ret


def create_and_mount(disk_list, mount_dir, mntArgsDict):
    mntArgsDict = mntArgsDict.copy()

    # create partitions
    hdd = HandyUtil.checkAndGetHdd(disk_list)
    InitDisk.initGptDisk(hdd, [
        ("100MiB", InitDisk.FsType.ESP),
        ("16MiB", InitDisk.FsType.NONE),
        ("*", InitDisk.FsType.NTFS),
    ])

    # get esp partition and root partition
    espParti = PartiUtil.diskToParti(hdd, 1)
    msrParti = PartiUtil.diskToParti(hdd, 2)
    rootParti = PartiUtil.diskToParti(hdd, 3)
    subprocess.check_call(["mkfs.vfat", espParti], stdout=subprocess.DEVNULL)                             # mkfs.vfat does not have a quiet option
    WinUtil.mkNtfs(rootParti)                                                                             # FIXME: maybe windows efi boot has no limit?

    # return
    ret = StorageLayoutImpl()
    ret._hdd = hdd
    ret._hddEspParti = espParti
    ret._hddMsrParti = msrParti
    ret._hddSysParti = rootParti
    ret._mnt = MountEfi(False, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)             # do mount during MountEfi initialization
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
        MountCommand.Mount(Util.rootfsDir, *Util.rootfsDirModeUidGid, obj.dev_sys, MountCommand.Mount.FsType.NTFS3, mnt_opt_list=tlist),
        MountCommand.Mount(Util.bootDir, *Util.bootDirModeUidGid, obj.dev_esp, MountCommand.Mount.FsType.VFAT, mnt_opt_list=(Util.bootDirMntOptList + tlistBoot), is_temp=True),
    ]

    MountEfi.mntParamsMergeMntArgReadOnly(ret, mntArgsDict)

    return ret
