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
import sys
import psutil
import pkgutil
from .util import Util, BtrfsUtil, LvmUtil
from . import errors


class StorageLayout:

    BOOT_MODE_BIOS = 1
    BOOT_MODE_EFI = 2

    @property
    def name(self):
        fn = sys.modules.get(self.__module__).__file__
        fn = os.path.basename(fn).replace(".py", "")
        return Util.modName2layoutName(fn)

    @property
    def boot_mode(self):
        raise NotImplementedError()

    @property
    def dev_rootfs(self):
        raise NotImplementedError()

    @property
    def dev_swap(self):
        raise NotImplementedError()

    def get_boot_disk(self):
        raise NotImplementedError()

    def check_swap_size(self):
        raise NotImplementedError()


def get_supported_storage_layouts():
    ret = []
    for mod in pkgutil.iter_modules(["."]):
        if mod.name.startswith("layout_"):
            ret.append(Util.modName2layoutName(mod.name))
    return ret


def create_storage_layout(layout_name, dry_run=False):
    for mod in pkgutil.iter_modules(["."]):
        if mod.name.startswith("layout_"):
            if layout_name == Util.modName2layoutName(mod.name):
                return mod.create(dry_run=dry_run)
    raise errors.StorageLayoutCreateError("layout \"%s\" not supported" % (layout_name))


def get_current_storage_layout():
    allLayoutNames = get_supported_storage_layouts()

    rootDev = None
    rootDevFs = None
    bootDev = None
    for pobj in psutil.disk_partitions():
        if pobj.mountpoint == "/":
            rootDev = pobj.device
            rootDevFs = pobj.fstype
        elif pobj.mountpoint == "/boot":
            bootDev = pobj.device
    assert rootDev is not None

    if bootDev is not None:
        # bcachefs related
        if Util.anyIn(["efi-bcachefs"], allLayoutNames):
            if rootDevFs == Util.fsTypeBcachefs:
                return _parseOneStorageLayout("efi-bcachefs", bootDev, rootDev)

        # btrfs related
        if Util.anyIn(["efi-bcache-btrfs", "efi-btrfs"], allLayoutNames):
            if rootDevFs == Util.fsTypeBtrfs:
                tlist = BtrfsUtil.getSlaveDevPathList(rootDev)          # only call btrfs related procedure when corresponding storage layout exists
                if any(re.fullmatch("/dev/bcache[0-9]+", x) is not None for x in tlist):
                    return _parseOneStorageLayout("efi-bcache-btrfs", bootDev, rootDev)
                else:
                    return _parseOneStorageLayout("efi-btrfs", bootDev, rootDev)

        # lvm related
        if Util.anyIn(["efi-bcache-lvm-ext4", "efi-lvm-ext4"], allLayoutNames):
            lvmInfo = Util.getBlkDevLvmInfo(rootDev)                    # only call lvm related procedure when corresponding storage layout exists
            if lvmInfo is not None:
                tlist = LvmUtil.getSlaveDevPathList(lvmInfo[0])
                if any(re.fullmatch("/dev/bcache[0-9]+", x) is not None for x in tlist):
                    return _parseOneStorageLayout("efi-bcache-lvm-ext4", bootDev, rootDev)
                else:
                    return _parseOneStorageLayout("efi-lvm-ext4", bootDev, rootDev)

        # simplest layout
        if Util.anyIn(["efi-ext4"], allLayoutNames):
            return _parseOneStorageLayout("efi-ext4", bootDev, rootDev)
    else:
        # lvm related
        if Util.anyIn(["bios-lvm-ext4"], allLayoutNames):
            if Util.getBlkDevLvmInfo(rootDev) is not None:              # only call lvm related procedure when corresponding storage layout exists
                return _parseOneStorageLayout("bios-lvm-ext4", bootDev, rootDev)

        # simplest layout
        if Util.anyIn(["bios-ext4"], allLayoutNames):
            return _parseOneStorageLayout("bios-ext4", bootDev, rootDev)

    raise errors.StorageLayoutParseError("", "unknown storage layout")


def detect_and_mount_storage_layout(mount_dir, mount_read_only=False):
    ssdList, hddList = Util.getDevPathListForFixedSsdAndHdd()
    if len(hddList) > 0:
        if len(ssdList) > 0:
            pass
        else:
            pass
    elif len(ssdList) > 0:
            pass
    else:
        raise errors.StorageLayoutParseError(errors.NO_VALID_LAYOUT)


def _parseOneStorageLayout(layoutName, bootDev, rootDev):
    modname = Util.layoutName2modName(layoutName)
    try:
        exec("import strict_hdds.%s" % (modname))
        f = eval("strict_hdds.%s.parse" % (modname))
        return f(bootDev, rootDev)
    except ModuleNotFoundError:
        raise errors.StorageLayoutParseError("", "unknown storage layout")


def _detectAndMountOneStorageLayout(layoutName, diskList, mountDir, mountOptions):
    modname = Util.layoutName2modName(layoutName)
    try:
        exec("import strict_hdds.%s" % (modname))
        f = eval("strict_hdds.%s.detect_and_mount" % (modname))
        return f(diskList, mountDir, mountOptions)
    except ModuleNotFoundError:
        raise errors.StorageLayoutParseError("", "unknown storage layout")
