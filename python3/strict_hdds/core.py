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


import os
import abc
import glob
import psutil
import functools
from .util import BcacheUtil, Util, GptUtil, BtrfsUtil, LvmUtil, PhysicalDiskMounts
from .handy import HandyUtil
from . import errors


class StorageLayout(abc.ABC):

    BOOT_MODE_BIOS = 1
    BOOT_MODE_EFI = 2

    @property
    def name(self):
        return HandyUtil.getStorageLayoutName(self.__class__)

    @property
    @abc.abstractmethod
    def boot_mode(self):
        pass

    @property
    @abc.abstractmethod
    def boot_disk(self):
        pass

    @property
    @abc.abstractmethod
    def mount_point(self):
        pass

    @abc.abstractmethod
    def umount_and_dispose(self):
        pass

    @abc.abstractmethod
    def get_mount_params(self, **kwargs):
        pass

    @abc.abstractmethod
    def is_read_only(self):
        pass

    @abc.abstractmethod
    def get_disk_list(self):
        pass

    def check(self, *kargs, auto_fix=False, error_callback=None):
        self._check_impl(Util.checkItemBasic, auto_fix=auto_fix, error_callback=functools.partial(errors.checkErrorCallback, error_callback))

    def opt_check(self, check_item, *kargs, auto_fix=False, error_callback=None):
        assert check_item != Util.checkItemBasic
        self._check_impl(check_item, *kargs, auto_fix=auto_fix, error_callback=functools.partial(errors.checkErrorCallback, error_callback))

    @abc.abstractmethod
    def _check_impl(self, check_item, *kargs, auto_fix=False, error_callback=None):
        pass


class MountParam:

    def __init__(self, dir_path, dir_mode, dir_uid, dir_gid, device, fstype, mnt_opt_list=[]):
        assert os.path.isabs(dir_path)
        assert dir_mode is not None
        assert isinstance(dir_uid, int)
        assert isinstance(dir_gid, int)
        assert device is not None
        assert fstype is not None
        assert mnt_opt_list is not None

        self.device = device
        self.mountpoint = dir_path
        self.fstype = fstype

        self.mnt_opt_list = mnt_opt_list
        self.mnt_dir_mode = dir_mode
        self.mnt_dir_uid = dir_uid
        self.mnt_dir_gid = dir_gid

    @property
    def opts(self):
        return ",".join(self.mnt_opt_list)


class RwController(abc.ABC):

    @abc.abstractmethod
    def is_writable(self):
        pass

    @abc.abstractmethod
    def to_read_write(self):
        pass

    @abc.abstractmethod
    def to_read_only(self):
        pass


def get_supported_storage_layout_names():
    selfDir = os.path.dirname(os.path.realpath(__file__))
    ret = []
    for fn in os.listdir(selfDir):
        if fn.startswith("layout_"):
            assert fn.endswith(".py")
            ret.append(Util.modName2layoutName(fn.replace(".py", "")))
    return sorted(ret)


def get_storage_layout(mount_dir="/"):
    allLayoutNames = get_supported_storage_layout_names()

    rootDev = None
    rootDevFs = None
    bootDev = None
    for pobj in psutil.disk_partitions():
        if pobj.mountpoint == mount_dir:
            rootDev = pobj.device
            rootDevFs = pobj.fstype
        elif pobj.mountpoint == os.path.join(mount_dir, "boot"):
            bootDev = pobj.device
    assert rootDev is not None

    if bootDev is not None:
        # bcachefs related
        if Util.anyIn(["efi-bcachefs"], allLayoutNames):
            if rootDevFs == Util.fsTypeBcachefs:
                return _parseOneStorageLayout("efi-bcachefs", bootDev, rootDev, mount_dir)

        # btrfs related
        if Util.anyIn(["efi-bcache-btrfs", "efi-btrfs"], allLayoutNames):
            if rootDevFs == Util.fsTypeBtrfs:
                tlist = BtrfsUtil.getSlaveDevPathList(mount_dir)                    # only call btrfs related procedure when corresponding storage layout exists
                if any(BcacheUtil.getBcacheDevFromDevPath(x) is not None for x in tlist):
                    return _parseOneStorageLayout("efi-bcache-btrfs", bootDev, rootDev, mount_dir)
                else:
                    return _parseOneStorageLayout("efi-btrfs", bootDev, rootDev, mount_dir)

        # lvm related
        if Util.anyIn(["efi-bcache-lvm-ext4", "efi-lvm-ext4"], allLayoutNames):
            if Util.cmdCallTestSuccess("lvm", "vgdisplay", LvmUtil.vgName):         # only call lvm related procedure when corresponding storage layout exists
                tlist = LvmUtil.getSlaveDevPathList(LvmUtil.vgName)
                if any(BcacheUtil.getBcacheDevFromDevPath(x) is not None for x in tlist):
                    return _parseOneStorageLayout("efi-bcache-lvm-ext4", bootDev, rootDev, mount_dir)
                else:
                    return _parseOneStorageLayout("efi-lvm-ext4", bootDev, rootDev, mount_dir)

        # simple layout
        if Util.anyIn(["efi-ext4"], allLayoutNames):
            if Util.getBlkDevFsType(rootDev) == Util.fsTypeExt4:
                return _parseOneStorageLayout("efi-ext4", bootDev, rootDev, mount_dir)
    else:
        # lvm related
        if Util.anyIn(["bios-lvm-ext4"], allLayoutNames):
            if Util.cmdCallTestSuccess("lvm", "vgdisplay", LvmUtil.vgName):         # only call lvm related procedure when corresponding storage layout exists
                return _parseOneStorageLayout("bios-lvm-ext4", bootDev, rootDev, mount_dir)

        # simple layout
        if Util.anyIn(["bios-ext4"], allLayoutNames):
            if Util.getBlkDevFsType(rootDev) == Util.fsTypeExt4:
                return _parseOneStorageLayout("bios-ext4", bootDev, rootDev, mount_dir)

        # simple layout
        if Util.anyIn(["bios-ntfs"], allLayoutNames):
            if Util.getBlkDevFsType(rootDev) == Util.fsTypeNtfs:
                return _parseOneStorageLayout("bios-ntfs", bootDev, rootDev, mount_dir)

        # simple layout
        if Util.anyIn(["bios-fat"], allLayoutNames):
            if Util.getBlkDevFsType(rootDev) == Util.fsTypeFat:
                return _parseOneStorageLayout("bios-fat", bootDev, rootDev, mount_dir)

    raise errors.StorageLayoutParseError("", "unknown storage layout")


def mount_storage_layout(mount_dir, layout_name=None, disk_list=None, **kwargs):
    if disk_list is None:
        disk_list = Util.getDevPathListForFixedDisk()
    if len(disk_list) == 0:
        raise errors.StorageLayoutParseError(errors.NO_DISK_WHEN_PARSE)

    if layout_name is not None:
        return _detectAndMountOneStorageLayout(layout_name, disk_list, mount_dir, kwargs)

    espPartiList = []
    normalPartiList = []
    for disk in disk_list:
        for devPath in glob.glob(disk + "*"):
            if devPath == disk:
                continue
            if GptUtil.isEspPartition(devPath):
                espPartiList.append(devPath)
            else:
                normalPartiList.append(devPath)

    allLayoutNames = get_supported_storage_layout_names()
    if len(espPartiList) > 0:
        # bcachefs related
        if Util.anyIn(["efi-bcachefs"], allLayoutNames):
            if any(Util.getBlkDevFsType(x) == Util.fsTypeBcachefs for x in normalPartiList):
                return _detectAndMountOneStorageLayout("efi-bcachefs", disk_list, mount_dir, kwargs)

        # btrfs related
        if Util.anyIn(["efi-btrfs"], allLayoutNames):
            if any(Util.getBlkDevFsType(x) == Util.fsTypeBtrfs for x in normalPartiList):
                return _detectAndMountOneStorageLayout("efi-btrfs", disk_list, mount_dir, kwargs)

        # bcache related
        if Util.anyIn(["efi-bcache-btrfs", "efi-bcache-lvm-ext4"], allLayoutNames):
            bcacheDevPathList = BcacheUtil.scanAndRegisterAllAndFilter(disk_list)    # only call bcache related procedure when corresponding storage layout exists
            if len(bcacheDevPathList) > 0:
                if any(Util.getBlkDevFsType(x) == Util.fsTypeBtrfs for x in bcacheDevPathList):
                    return _detectAndMountOneStorageLayout("efi-bcache-btrfs", disk_list, mount_dir, kwargs)
                else:
                    return _detectAndMountOneStorageLayout("efi-bcache-lvm-ext4", disk_list, mount_dir, kwargs)

        # lvm related
        if Util.anyIn(["efi-lvm-ext4"], allLayoutNames):
            LvmUtil.activateAll()                                           # only call lvm related procedure when corresponding storage layout exists
            if LvmUtil.vgName in LvmUtil.getVgList():
                return _detectAndMountOneStorageLayout("efi-lvm-ext4", disk_list, mount_dir, kwargs)

        # simple layout
        if Util.anyIn(["efi-ext4"], allLayoutNames):
            if any([Util.getBlkDevFsType(x) == Util.fsTypeExt4 for x in normalPartiList]):
                return _detectAndMountOneStorageLayout("efi-ext4", disk_list, mount_dir, kwargs)
    else:
        # lvm related
        if Util.anyIn(["bios-lvm-ext4"], allLayoutNames):
            LvmUtil.activateAll()                                       # only call lvm related procedure when corresponding storage layout exists
            if LvmUtil.vgName in LvmUtil.getVgList():
                return _detectAndMountOneStorageLayout("bios-lvm-ext4", disk_list, mount_dir, kwargs)

        # simple layout
        if Util.anyIn(["bios-ext4"], allLayoutNames):
            if any([Util.getBlkDevFsType(x) == Util.fsTypeExt4 for x in normalPartiList]):
                return _detectAndMountOneStorageLayout("bios-ext4", disk_list, mount_dir, kwargs)

        # simple layout
        if Util.anyIn(["bios-ntfs"], allLayoutNames):
            if any([Util.getBlkDevFsType(x) == Util.fsTypeNtfs for x in normalPartiList]):
                return _detectAndMountOneStorageLayout("bios-ntfs", disk_list, mount_dir, kwargs)

        # simple layout
        if Util.anyIn(["bios-fat"], allLayoutNames):
            if any([Util.getBlkDevFsType(x) == Util.fsTypeFat for x in normalPartiList]):
                return _detectAndMountOneStorageLayout("bios-fat", disk_list, mount_dir, kwargs)

    raise errors.StorageLayoutParseError("", "unknown storage layout")


def create_and_mount_storage_layout(layout_name, mount_dir, disk_list=None, **kwargs):
    if disk_list is None:
        disk_list = Util.getDevPathListForFixedDisk()

    modname = Util.layoutName2modName(layout_name)
    try:
        exec("from . import %s" % (modname))
        f = eval("%s.create_and_mount" % (modname))
        return f(disk_list, mount_dir, kwargs)
    except ModuleNotFoundError:
        raise errors.StorageLayoutCreateError("layout \"%s\" not supported" % (layout_name))


def _parseOneStorageLayout(layoutName, bootDev, rootDev, mountDir):
    modname = Util.layoutName2modName(layoutName)
    try:
        exec("from . import %s" % (modname))
        f = eval("%s.parse" % (modname))
        return f(bootDev, rootDev, mountDir)
    except ModuleNotFoundError:
        raise errors.StorageLayoutParseError("", "unknown storage layout")


def _detectAndMountOneStorageLayout(layoutName, diskList, mountDir, mntArgsDict):
    modname = Util.layoutName2modName(layoutName)
    try:
        exec("from . import %s" % (modname))
        f = eval("%s.detect_and_mount" % (modname))
        return f(diskList, mountDir, mntArgsDict)
    except ModuleNotFoundError:
        raise errors.StorageLayoutParseError("", "unknown storage layout")
