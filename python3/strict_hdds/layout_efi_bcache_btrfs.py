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
from .util import Util, BcacheUtil, BtrfsUtil
from .types import MountCommand
from .handy import EfiCacheGroup, Bcache, SubVols, SubVolsBtrfs, MountEfi, HandyCg, HandyBcache, DisksChecker, HandyUtil
from . import errors
from . import StorageLayout


class StorageLayoutImpl(StorageLayout):
    """Layout:
           /dev/sda                      SSD, GPT (cache-disk)
               /dev/sda1                 ESP partition
               /dev/sda2                 swap device
               /dev/sda3                 bcache cache device
           /dev/sdb                      Non-SSD, GPT
               /dev/sdb1                 reserved ESP partition
               /dev/sdb2                 bcache backing device
           /dev/sdc                      Non-SSD, GPT
               /dev/sdc1                 reserved ESP partition
               /dev/sdc2                 bcache backing device
           /dev/bcache0:/dev/bcache1     root device, btrfs
              /dev/bcache0               corresponds to /dev/sdb2, btrfs device
              /dev/bcache1               corresponds to /dev/sdc2, btrfs device
       OS:
           1. Linux
       Description:
           1. /dev/sda1 and /dev/sd{b,c}1 must has the same size
           2. /dev/sda1, /dev/sda2 and /dev/sda3 is order-sensitive, no extra partition is allowed
           3. /dev/sd{b,c}1 and /dev/sd{b,c}2 is order-sensitive, no extra partition is allowed
           4. cache-disk is optional, and only one cache-disk is allowed at most
           5. cache-disk can have no swap partition, /dev/sda2 would be the cache device then
           6. extra harddisk is allowed to exist
    """

    def __init__(self):
        self._cg = None                     # EfiCacheGroup
        self._bcache = None                 # Bcache
        self._subvols = None                # SubVolsBtrfs
        self._mnt = None                    # MountEfi

    @property
    def boot_mode(self):
        return StorageLayout.BOOT_MODE_EFI

    @EfiCacheGroup.proxy
    @property
    def boot_disk(self):
        pass

    @MountEfi.proxy
    @property
    def mount_point(self):
        pass

    @property
    def dev_rootfs(self):
        return self._bcache.get_all_bcache_dev_list()[0]

    @EfiCacheGroup.proxy
    @property
    def dev_boot(self):
        pass

    @EfiCacheGroup.proxy
    @property
    def dev_swap(self):
        pass

    @SubVols.proxy
    @property
    def snapshot(self):
        pass

    def umount_and_dispose(self):
        if True:
            self._mnt.umount()
            del self._mnt
        if True:
            self._bcache.stop_all()
            del self._bcache
        if True:
            del self._cg

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
        # FIXME: btrfs balance
        pass

    @EfiCacheGroup.proxy
    def get_esp(self):
        pass

    @EfiCacheGroup.proxy
    def get_pending_esp_list(self):
        pass

    @EfiCacheGroup.proxy
    def sync_esp(self, dst):
        pass

    @EfiCacheGroup.proxy
    def get_disk_list(self):
        pass

    @EfiCacheGroup.proxy
    def get_ssd(self):
        pass

    @EfiCacheGroup.proxy
    def get_ssd_esp_partition(self):
        pass

    @EfiCacheGroup.proxy
    def get_ssd_swap_partition(self):
        pass

    @EfiCacheGroup.proxy
    def get_ssd_cache_partition(self):
        pass

    @EfiCacheGroup.proxy
    def get_hdd_list(self):
        pass

    @EfiCacheGroup.proxy
    def get_hdd_esp_partition(self, disk):
        pass

    @EfiCacheGroup.proxy
    def get_hdd_data_partition(self, disk):
        pass

    def get_hdd_bcache_dev(self, disk):
        return self._bcache.get_bcache_dev(disk)

    @EfiCacheGroup.proxy
    def get_swap_size(self):
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

        if Util.isBlkDevSsdOrHdd(disk):
            assert self._cg.get_ssd() is None
            self._mnt.umount_esp(self._cg.get_hdd_esp_partition(self._cg.boot_disk))
            self._cg.add_ssd(disk, "bcache")
            self._bcache.add_cache(self._cg.get_ssd_cache_partition())
            self._mnt.mount_esp(self._cg.get_ssd_esp_partition())
            return True
        else:
            self._cg.add_hdd(disk, "bcache")
            self._bcache.add_backing(self._cg.get_ssd_cache_partition(), disk, self._cg.get_hdd_data_partition(disk))
            BtrfsUtil.addDiskToBtrfs(self._bcache.get_bcache_dev(disk), self._mnt.mount_point)
            assert disk != self._cg.boot_disk
            return False

    def remove_disk(self, disk):
        assert disk is not None

        if self._mnt.get_bootdir_rw_controller().is_writable():
            raise errors.StorageLayoutRemoveDiskError(disk, errors.BOOTDIR_NOT_RO)

        if disk == self._cg.get_ssd():
            # check if swap is in use
            if self._cg.get_ssd_swap_partition() is not None:
                if Util.isSwapFileOrPartitionBusy(self._cg.get_ssd_swap_partition()):
                    raise errors.StorageLayoutRemoveDiskError(disk, errors.SWAP_IS_IN_USE)

            # remove
            self._mnt.umount_esp(self._cg.get_ssd_esp_partition())
            self._bcache.remove_cache(self._cg.get_ssd_cache_partition())
            Util.waitUntilHarddiskNotBusy(self._cg.get_ssd())        # sometimes device is still busy after removed from cache set
            self._cg.remove_ssd()

            # boot disk change
            self._mnt.mount_esp(self._cg.get_hdd_esp_partition(self._cg.boot_disk))
            return True

        if disk in self._cg.get_hdd_list():
            # check for last hdd
            if len(self._cg.get_hdd_list()) <= 1:
                raise errors.StorageLayoutRemoveDiskError(disk, errors.CAN_NOT_REMOVE_LAST_HDD)

            # test boot disk change
            if self._cg.get_ssd() is None and disk == self._cg.boot_disk:
                bChange = True
            else:
                bChange = False

            # remove
            if bChange:
                self._mnt.umount_esp(self._cg.get_hdd_esp_partition(disk))
            Util.cmdCall("btrfs", "device", "delete", self._bcache.get_bcache_dev(disk), self._mnt.mount_point)
            self._bcache.remove_backing(disk)
            self._cg.remove_hdd(disk)

            # boot disk change
            if bChange:
                self._mnt.mount_esp(self._cg.get_disk_esp_partition(self._cg.boot_disk))
                return True
            else:
                return False

        assert False

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
            with DisksChecker(self._cg.get_disk_list()) as dc:
                dc.check_logical_sector_size(auto_fix, error_callback)
                dc.check_boot_sector(auto_fix, error_callback)
                dc.check_partition_type("gpt", auto_fix, error_callback)
                dc.check_partition_uuid(auto_fix, error_callback)
            self._cg.check_ssd(auto_fix, error_callback)
            self._cg.check_esp(auto_fix, error_callback)
            self._cg.check_file_system_uuid(auto_fix, error_callback)
            self._bcache.check(auto_fix, error_callback)
            self._subvols.check(auto_fix, error_callback)
        elif check_item == "bcache-write-mode":
            self._bcache.check_write_mode(kargs[0], auto_fix, error_callback)
        elif check_item == "swap":
            self._cg.check_swap(auto_fix, error_callback)
        elif check_item == "mount-write-mode":
            self._mnt.check_mount_write_mode(auto_fix, error_callback)
        else:
            assert False


def parse(boot_dev, root_dev, mount_dir):
    if boot_dev is None:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.BOOT_DEV_NOT_EXIST)
    if Util.getBlkDevFsType(root_dev) != Util.fsTypeBtrfs:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.ROOT_PARTITION_FS_SHOULD_BE(Util.fsTypeBtrfs))

    # bcache device list
    bcacheDevPathList = BtrfsUtil.getSlaveDevPathList(mount_dir)
    for bcacheDevPath in bcacheDevPathList:
        if BcacheUtil.getBcacheDevFromDevPath(bcacheDevPath) is None:
            raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), "\"%s\" has non-bcache slave device" % (root_dev))

    # ssd, hdd_list, boot_disk
    ssd, hddList = HandyBcache.getSsdAndHddListFromBcacheDevPathList(HandyUtil.getStorageLayoutName(StorageLayoutImpl), bcacheDevPathList)
    ssdEspParti, ssdSwapParti, ssdCacheParti = HandyCg.checkAndGetSsdPartitions(HandyUtil.getStorageLayoutName(StorageLayoutImpl), ssd)
    bootHdd = HandyCg.checkAndGetBootHddFromBootDev(HandyUtil.getStorageLayoutName(StorageLayoutImpl), boot_dev, ssdEspParti, hddList)

    # get mntArgsDict from mount options
    mntArgsDict = dict()
    SubVolsBtrfs.mntArgsDictSetSnapshot(HandyUtil.getStorageLayoutName(StorageLayoutImpl), mount_dir, mntArgsDict)
    MountEfi.mntArgsDictSetReadOnly(HandyUtil.getStorageLayoutName(StorageLayoutImpl), mount_dir, mntArgsDict)

    # return
    ret = StorageLayoutImpl()
    ret._cg = EfiCacheGroup(ssd=ssd, ssdEspParti=ssdEspParti, ssdSwapParti=ssdSwapParti, ssdCacheParti=ssdCacheParti, hddList=hddList, bootHdd=bootHdd)
    ret._bcache = Bcache(keyList=hddList, bcacheDevPathList=bcacheDevPathList)
    ret._subvols = SubVolsBtrfs(mount_dir, snapshot=mntArgsDict.get("snapshot", None))
    ret._mnt = MountEfi(True, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)
    return ret


def detect_and_mount(disk_list, mount_dir, mntArgsDict):
    mntArgsDict = mntArgsDict.copy()

    # scan
    bcacheDevPathList = BcacheUtil.scanAndRegisterAllAndFilter(disk_list)
    bcacheDevPathList = [x for x in bcacheDevPathList if Util.getBlkDevFsType(x) == Util.fsTypeBtrfs]
    if len(bcacheDevPathList) == 0:
        raise errors.StorageLayoutParseError(HandyUtil.getStorageLayoutName(StorageLayoutImpl), errors.DISK_NOT_FOUND)

    # ssd, hdd_list, boot_disk
    ssd, hddList = HandyBcache.getSsdAndHddListFromBcacheDevPathList(HandyUtil.getStorageLayoutName(StorageLayoutImpl), bcacheDevPathList)
    HandyCg.checkExtraDisks(HandyUtil.getStorageLayoutName(StorageLayoutImpl), ssd, hddList, disk_list)
    ssdEspParti, ssdSwapParti, ssdCacheParti = HandyCg.checkAndGetSsdPartitions(HandyUtil.getStorageLayoutName(StorageLayoutImpl), ssd)
    bootHdd = HandyCg.checkAndGetBootHddAndBootDev(HandyUtil.getStorageLayoutName(StorageLayoutImpl), ssdEspParti, hddList)[0]

    # return
    ret = StorageLayoutImpl()
    ret._cg = EfiCacheGroup(ssd=ssd, ssdEspParti=ssdEspParti, ssdSwapParti=ssdSwapParti, ssdCacheParti=ssdCacheParti, hddList=hddList, bootHdd=bootHdd)
    ret._bcache = Bcache(keyList=hddList, bcacheDevPathList=bcacheDevPathList)
    ret._subvols = SubVolsBtrfs(mount_dir, snapshot=mntArgsDict.get("snapshot", None))
    ret._mnt = MountEfi(False, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)    # do mount during MountEfi initialization
    return ret


def create_and_mount(disk_list, mount_dir, mntArgsDict):
    mntArgsDict = mntArgsDict.copy()

    # add disks to cache group
    cg = EfiCacheGroup()
    HandyCg.checkAndAddDisks(cg, *Util.splitSsdAndHddFromFixedDiskDevPathList(disk_list), "bcache")

    # create bcache
    bcache = Bcache()
    for hdd in cg.get_hdd_list():
        # hdd partition 2: make them as backing device
        bcache.add_backing(None, hdd, cg.get_hdd_data_partition(hdd))
    if cg.get_ssd() is not None:
        # ssd partition 3: make it as cache device
        bcache.add_cache(cg.get_ssd_cache_partition())

    # create btrfs
    Util.cmdCall("mkfs.btrfs", "-f", "-d", "single", "-m", "single", *bcache.get_all_bcache_dev_list())
    SubVolsBtrfs.initializeFs(bcache.get_all_bcache_dev_list()[0], _devMntOptList(bcache))

    # return
    ret = StorageLayoutImpl()
    ret._cg = cg
    ret._bcache = bcache
    ret._subvols = SubVolsBtrfs(mount_dir, snapshot=mntArgsDict.get("snapshot", None))
    ret._mnt = MountEfi(False, mount_dir, functools.partial(_getMntParams, ret), mntArgsDict)    # do mount during MountEfi initialization
    return ret


def _getMntParams(obj, mntArgsDict):
    tlist = _devMntOptList(obj._bcache)
    if "extra_mount_options_for_root_dev" in mntArgsDict:
        assert mntArgsDict["extra_mount_options_for_root_dev"] != ""
        tlist += mntArgsDict.pop("extra_mount_options_for_root_dev").split(",")

    tlistBoot = []
    if "extra_mount_options_for_boot_dev" in mntArgsDict:
        assert mntArgsDict["extra_mount_options_for_boot_dev"] != ""
        tlistBoot += mntArgsDict.pop("extra_mount_options_for_boot_dev").split(",")

    ret = []
    for dirPath, dirMode, dirUid, dirGid, mntOptList in SubVolsBtrfs.getParamsForMountWithoutSnapshot():
        ret.append(MountCommand.Mount(dirPath, dirMode, dirUid, dirGid, obj.dev_rootfs, Util.fsTypeBtrfs, mnt_opt_list=(mntOptList + tlist)))
    ret.append(MountCommand.Mount(Util.bootDir, *Util.bootDirModeUidGid, obj.dev_boot, Util.fsTypeFat, mnt_opt_list=(Util.bootDirMntOptList + tlistBoot)))

    SubVolsBtrfs.mntParamsMergeMntArgSnapshot(ret, mntArgsDict)
    MountEfi.mntParamsMergeMntArgReadOnly(ret, mntArgsDict)

    return ret


def _devMntOptList(bcache):
    return ["device=%s" % (x) for x in bcache.get_all_bcache_dev_list()]
