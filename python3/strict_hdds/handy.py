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
import re
import sys
import abc
import glob
import time
import struct
import parted
from .util import Util, PartiUtil, GptUtil, BcacheUtil, PhysicalDiskMounts, TmpMount
from .types import MountCommand, RwController
from . import errors


class EfiMultiDisk:

    @staticmethod
    def proxy(func):
        if isinstance(func, property):
            def f_get(self):
                return getattr(self._md, func.fget.__name__)
            f_get.__name__ = func.fget.__name__
            return property(f_get)
        else:
            def f(self, *args):
                return getattr(self._md, func.__name__)(*args)
            return f

    def __init__(self, diskList=[], bootHdd=None):
        # assign self._hddList
        assert diskList is not None
        self._hddList = sorted(diskList)

        # assign self._bootHdd
        if len(self._hddList) > 0:
            if bootHdd is None:
                bootHdd = self._hddList[0]
            else:
                assert bootHdd in self._hddList
        else:
            assert bootHdd is None
        self._bootHdd = bootHdd

    @property
    def boot_disk(self):
        return self._bootHdd

    @property
    def dev_boot(self):
        return self.get_esp()

    def get_esp(self):
        if self._bootHdd is not None:
            return PartiUtil.diskToParti(self._bootHdd, 1)
        else:
            return None

    def get_pending_esp_list(self):
        ret = []
        for hdd in self._hddList:
            if self._bootHdd is None or hdd != self._bootHdd:
                ret.append(PartiUtil.diskToParti(hdd, 1))
        return ret

    def sync_esp(self, dst):
        assert self.get_esp() is not None
        assert dst is not None and dst in self.get_pending_esp_list()
        Util.syncBlkDev(self.get_esp(), dst, mountPoint1=Util.bootDir)

    def get_disk_list(self):
        return self._hddList

    def get_disk_esp_partition(self, disk):
        assert disk in self._hddList
        return PartiUtil.diskToParti(disk, 1)

    def get_disk_data_partition(self, disk):
        assert disk in self._hddList
        return PartiUtil.diskToParti(disk, 2)

    def add_disk(self, disk, fsType):
        assert disk is not None and disk not in self._hddList

        # create disk
        try:
            if self._bootHdd is None:
                fsType1 = "esp"
            else:
                fsType1 = "fat32"
            Util.initializeDisk(disk, "gpt", [
                ("%dMiB" % (Util.getEspSizeInMb()), fsType1),
                ("*", fsType),
            ])

            # partition1: pending ESP partition
            parti = PartiUtil.diskToParti(disk, 1)
            if self._bootHdd is None:
                Util.cmdCall("mkfs.vfat", parti)
            else:
                # FIXME: change to copyFatFs
                Util.cmdCall("mkfs.vfat", parti)
                Util.syncBlkDev(PartiUtil.diskToParti(self._bootHdd, 1), parti, mountPoint1=Util.bootDir)

            # partition2: data partition, leave it to user
            pass
        except BaseException:
            Util.wipeHarddisk(disk)
            raise

        # add disk
        self._hddList.append(disk)
        self._hddList.sort()

        # change boot disk if neccessary
        if self._bootHdd is None:
            assert len(self._hddList) == 1
            self._bootHdd = disk

    def remove_disk(self, disk):
        assert disk is not None and disk in self._hddList

        # remove disk
        self._hddList.remove(disk)

        # wipe disk
        Util.wipeHarddisk(disk)

        # change boot disk if neccessary
        if self._bootHdd == disk:
            if len(self._bootHdd) > 0:
                Util.toggleEspPartition(PartiUtil.diskToParti(self._hddList[0], 1), True)
                self._bootHdd = self._hddList[0]
            else:
                self._bootHdd = None

    def check_esp(self, auto_fix, error_callback):
        for hdd in self._hddList:
            parti = self.get_disk_esp_partition(hdd)
            if Util.getBlkDevSize(parti) != Util.getEspSize():
                # no way to auto fix
                error_callback(errors.CheckCode.ESP_SIZE_INVALID, parti)

    def check_file_system_uuid(self, auto_fix, error_callback):
        tlist = []
        for hdd in self._hddList:
            tlist.append(self.get_disk_esp_partition(hdd))
            tlist.append(self.get_disk_data_partition(hdd))

        fsUuidDict = dict()
        for partiDevPath in tlist:
            fsUuid = Util.getBlkDevFsUuid(partiDevPath)
            if fsUuid == "":
                error_callback(errors.CheckCode.TRIVIAL, "%s has no file system UUID" % (partiDevPath))
                continue
            if fsUuid in fsUuidDict:
                error_callback(errors.CheckCode.TRIVIAL, "%s and %s has same file system UUID" % (fsUuidDict[fsUuid], partiDevPath))
                continue
            fsUuidDict[fsUuid] = partiDevPath


class EfiCacheGroup:

    @staticmethod
    def proxy(func):
        if isinstance(func, property):
            def f_get(self):
                return getattr(self._cg, func.fget.__name__)
            f_get.__name__ = func.fget.__name__
            return property(f_get)
        else:
            def f(self, *args):
                return getattr(self._cg, func.__name__)(*args)
            return f

    def __init__(self, ssd=None, ssdEspParti=None, ssdCacheParti=None, hddList=[], bootHdd=None):
        # assign self._ssd and friends
        self._ssd = ssd
        if self._ssd is not None:
            self._ssdEspParti = PartiUtil.diskToParti(ssd, 1)
            self._ssdCacheParti = PartiUtil.diskToParti(ssd, 2)
        else:
            self._ssdEspParti = None
            self._ssdCacheParti = None
        assert self._ssdEspParti == ssdEspParti
        assert self._ssdCacheParti == ssdCacheParti

        # assign self._hddList
        assert hddList is not None
        self._hddList = sorted(hddList)

        # assign self._bootHdd
        if self._ssd is not None:
            assert bootHdd is None
        else:
            if len(self._hddList) > 0:
                if bootHdd is None:
                    bootHdd = self._hddList[0]
                else:
                    assert bootHdd in self._hddList
            else:
                assert bootHdd is None
        self._bootHdd = bootHdd

    @property
    def boot_disk(self):
        return self._ssd if self._ssd is not None else self._bootHdd

    @property
    def dev_boot(self):
        return self.get_esp()

    def get_esp(self):
        if self._ssd is not None:
            return self._ssdEspParti
        elif self._bootHdd is not None:
            return PartiUtil.diskToParti(self._bootHdd, 1)
        else:
            return None

    def get_pending_esp_list(self):
        ret = []
        for hdd in self._hddList:
            if self._bootHdd is None or hdd != self._bootHdd:
                ret.append(PartiUtil.diskToParti(hdd, 1))
        return ret

    def sync_esp(self, dst):
        assert self.get_esp() is not None
        assert dst is not None and dst in self.get_pending_esp_list()
        Util.syncBlkDev(self.get_esp(), dst, mountPoint1=Util.bootDir)

    def get_disk_list(self):
        if self._ssd is not None:
            return [self._ssd] + self._hddList
        else:
            return self._hddList

    def get_ssd(self):
        return self._ssd

    def get_ssd_esp_partition(self):
        assert self._ssd is not None
        assert self._ssdEspParti is not None
        assert self._bootHdd is None
        return self._ssdEspParti

    def get_ssd_cache_partition(self):
        assert self._ssd is not None
        assert self._ssdCacheParti is not None
        assert self._bootHdd is None
        return self._ssdCacheParti

    def get_hdd_list(self):
        return self._hddList

    def get_hdd_esp_partition(self, disk):
        assert disk in self._hddList
        return PartiUtil.diskToParti(disk, 1)

    def get_hdd_data_partition(self, disk):
        assert disk in self._hddList
        return PartiUtil.diskToParti(disk, 2)

    def add_ssd(self, ssd, fsType):
        assert ssd is not None and self._ssd is None and ssd not in self._hddList

        self._ssd = ssd
        self._ssdEspParti = PartiUtil.diskToParti(ssd, 1)
        self._ssdCacheParti = PartiUtil.diskToParti(ssd, 2)
        oldBootHdd = self._bootHdd
        try:
            # create partitions
            Util.initializeDisk(self._ssd, "gpt", [
                ("%dMiB" % (Util.getEspSizeInMb()), "esp"),
                ("*", fsType),
            ])

            # partition1: ESP partition
            if self._bootHdd is not None:
                # FIXME: change to copyFatFs
                Util.cmdCall("mkfs.vfat", self._ssdEspParti)
                Util.syncBlkDev(PartiUtil.diskToParti(self._bootHdd, 1), self._ssdEspParti)
            else:
                Util.cmdCall("mkfs.vfat", self._ssdEspParti)

            # partition2: cache partition, leave it to caller
            pass

            # change boot device
            if self._bootHdd is not None:
                Util.toggleEspPartition(PartiUtil.diskToParti(self._bootHdd, 1), False)
                self._bootHdd = None
        except BaseException:
            # FIXME: should assert Util.isEspPartition(PartiUtil.diskToParti(self._bootHdd, 1), True))
            assert self._bootHdd == oldBootHdd
            Util.wipeHarddisk(self._ssd)
            self._ssdCacheParti = None
            self._ssdEspParti = None
            self._ssd = None
            raise

    def remove_ssd(self):
        assert self._ssd is not None

        # partition1: ESP partition
        self._ssdEspParti = None

        # partition2: cache partition, the caller should have processed it
        self._ssdCacheParti = None

        # wipe disk
        Util.wipeHarddisk(self._ssd)
        self._ssd = None

        # change boot device
        assert self._bootHdd is None
        if len(self._hddList) > 0:
            Util.toggleEspPartition(PartiUtil.diskToParti(self._hddList[0], 1), True)
            self._bootHdd = self._hddList[0]

    def add_hdd(self, hdd, fsType):
        assert hdd is not None and hdd not in self._hddList

        # create disk
        try:
            if self._ssd is None and self._bootHdd is None:
                fsType1 = "esp"
            else:
                fsType1 = "fat32"

            Util.initializeDisk(hdd, "gpt", [
                ("%dMiB" % (Util.getEspSizeInMb()), fsType1),
                ("*", fsType),
            ])

            # partition1: pending ESP partition
            parti = PartiUtil.diskToParti(hdd, 1)
            if self._ssd is not None:
                # FIXME: change to copyFatFs
                Util.cmdCall("mkfs.vfat", parti)
                Util.syncBlkDev(self._ssdEspParti, parti, mountPoint1=Util.bootDir)
            elif self._bootHdd is not None:
                # FIXME: change to copyFatFs
                Util.cmdCall("mkfs.vfat", parti)
                Util.syncBlkDev(PartiUtil.diskToParti(self._bootHdd, 1), parti, mountPoint1=Util.bootDir)
            else:
                Util.cmdCall("mkfs.vfat", parti)

            # partition2: data partition, leave it to user
            pass
        except BaseException:
            Util.wipeHarddisk(hdd)
            raise

        # add disk
        self._hddList.append(hdd)
        self._hddList.sort()

        # change boot disk if neccessary
        if self._ssd is None and self._bootHdd is None:
            assert len(self._hddList) == 1
            self._bootHdd = hdd

    def remove_hdd(self, hdd):
        assert hdd is not None and hdd in self._hddList

        # remove disk
        self._hddList.remove(hdd)

        # wipe disk
        Util.wipeHarddisk(hdd)

        # change boot disk if neccessary
        if self._ssd is None:
            assert self._bootHdd is not None
            if self._bootHdd == hdd:
                if len(self._bootHdd) > 0:
                    Util.toggleEspPartition(PartiUtil.diskToParti(self._hddList[0], 1), True)
                    self._bootHdd = self._hddList[0]
                else:
                    self._bootHdd = None

    def check_ssd(self, auto_fix, error_callback):
        if self._ssd is None:
            # no way to auto fix
            error_callback(errors.CheckCode.TRIVIAL, "It would be better to add a cache device.")

    def check_esp(self, auto_fix, error_callback):
        if self._ssd is not None:
            tlist = [self._ssdEspParti]
        else:
            tlist = []
        tlist += [self.get_hdd_esp_partition(x) for x in self._hddList]

        for parti in tlist:
            if Util.getBlkDevSize(parti) != Util.getEspSize():
                # no way to auto fix
                error_callback(errors.CheckCode.ESP_SIZE_INVALID)

    def check_file_system_uuid(self, auto_fix, error_callback):
        if self._ssd is not None:
            tlist = [self._ssdEspParti, self._ssdCacheParti]
        else:
            tlist = []
        for hdd in self._hddList:
            tlist.append(self.get_hdd_esp_partition(hdd))
            tlist.append(self.get_hdd_data_partition(hdd))

        fsUuidDict = dict()
        for partiDevPath in tlist:
            fsUuid = Util.getBlkDevFsUuid(partiDevPath)
            if fsUuid == "":
                error_callback(errors.CheckCode.TRIVIAL, "%s has no file system UUID" % (partiDevPath))
                continue
            if fsUuid in fsUuidDict:
                error_callback(errors.CheckCode.TRIVIAL, "%s and %s has same file system UUID" % (fsUuidDict[fsUuid], partiDevPath))
                continue
            fsUuidDict[fsUuid] = partiDevPath


class Bcache:

    def __init__(self, keyList=[], bcacheDevPathList=[]):
        self._backingDict = Util.keyValueListToDict(keyList, bcacheDevPathList)

        self._cacheDevSet = set()
        for bcacheDevPath in bcacheDevPathList:
            self._cacheDevSet.update(set(BcacheUtil.getSlaveDevPathList(bcacheDevPath)[:-1]))

    def get_bcache_dev(self, key):
        return self._backingDict[key]

    def get_all_bcache_dev_list(self):
        return list(self._backingDict.values())

    def add_cache(self, cacheDevPath):
        BcacheUtil.makeDevice(cacheDevPath, False)
        BcacheUtil.registerCacheDevice(cacheDevPath)
        try:
            BcacheUtil.attachCacheDevice(self._backingDict.values(), cacheDevPath)
            self._cacheDevSet.add(cacheDevPath)
        except BaseException:
            BcacheUtil.unregisterCacheDevice(cacheDevPath)
            raise

    def add_backing(self, cacheDevPath, key, devPath):
        BcacheUtil.makeDevice(devPath, True)

        bcacheDevPath = None
        if True:
            bcacheList = glob.glob("/dev/bcache*")
            BcacheUtil.registerBackingDevice(devPath)
            devName = os.path.basename(devPath)
            for i in range(0, 10):
                for fullfn in glob.glob("/dev/bcache*"):
                    if fullfn not in bcacheList:
                        if re.fullmatch("/dev/bcache[0-9]+", fullfn):
                            bcachePath = os.path.realpath("/sys/class/block/" + devName + "/bcache")
                            if os.path.basename(os.path.dirname(bcachePath)) == devName:
                                bcacheDevPath = fullfn
                                break
                        bcacheList.append(fullfn)
                if bcacheDevPath is not None:
                    break
                time.sleep(1)
            if bcacheDevPath is None:
                raise Exception("register backing device failed, corresponding bcache device is not found")

        try:
            if cacheDevPath is not None:
                BcacheUtil.attachCacheDevice([bcacheDevPath], cacheDevPath)
            self._backingDict[key] = bcacheDevPath
            return bcacheDevPath
        except BaseException:
            BcacheUtil.stopBackingDevice(bcacheDevPath)
            raise

    def remove_cache(self, cacheDevPath):
        BcacheUtil.unregisterCacheDevice(cacheDevPath)
        self._cacheDevSet.remove(cacheDevPath)

    def remove_backing(self, key):
        BcacheUtil.stopBackingDevice(self._backingDict[key])
        del self._backingDict[key]

    def stop_all(self):
        for bcacheDevPath in self._backingDict.values():
            BcacheUtil.stopBackingDevice(bcacheDevPath)

    def check(self, auto_fix=False, error_callback=None):
        # check mode is consistent
        lastDevPath = None
        lastMode = None
        for bcacheDevPath in self._backingDict.values():
            mode = BcacheUtil.getMode(bcacheDevPath)
            if lastMode is not None:
                if mode != lastMode:
                    error_callback(errors.CheckCode.TRIVIAL, "BCACHE device %s and %s have inconsistent write mode." % (lastDevPath, bcacheDevPath))
            else:
                lastDevPath = bcacheDevPath
                lastMode = mode

    def check_write_mode(self, mode, auto_fix=False, error_callback=None):
        assert mode in ["writethrough", "writeback"]
        for bcacheDevPath in self._backingDict.values():
            if BcacheUtil.getMode(bcacheDevPath) != mode:
                if auto_fix:
                    Bcache.setMode(mode)
                else:
                    error_callback(errors.CheckCode.TRIVIAL, "BCACHE device %s should be configured as writeback mode." % (bcacheDevPath))


class SwapFile:

    @staticmethod
    def proxy(func):
        if isinstance(func, property):
            def f_get(self):
                return getattr(self._swap, func.fget.__name__)
            f_get.__name__ = func.fget.__name__
            return property(f_get)
        else:
            def f(self, *args):
                return getattr(self._swap, func.__name__)(*args)
            return f

    def __init__(self, bSwapFile):
        self._bSwapFile = bSwapFile

    def get_swap_size(self):
        return Util.getSwapSize()

    def create_swap_file(self):
        assert not self._bSwapFile
        Util.createSwapFile(Util.swapFilepath)
        self._bSwapFile = True

    def remove_swap_file(self):
        assert self._bSwapFile
        os.remove(Util.swapFilepath)
        self._bSwapFile = False

    def has_swap_file(self):
        return self._bSwapFile

    def get_swap_file_path(self):
        assert self._bSwapFile
        return Util.swapFilepath

    def check(self, auto_fix, error_callback):
        if not self._bSwapFile:
            error_callback(errors.CheckCode.SWAP_NOT_ENABLED)
        else:
            if os.path.getsize(Util.swapFilepath) < Util.getSwapSize():
                if auto_fix:
                    if not Util.isSwapFileOrPartitionBusy(Util.swapFilepath):
                        self.remove_swap_file()
                        self.create_swap_file()
                        return
                error_callback(errors.CheckCode.SWAP_SIZE_TOO_SMALL, "file")


class SubVols(abc.ABC):

    @classmethod
    def initializeFs(cls, devPath, mntOptList):
        with TmpMount(devPath, options=",".join(mntOptList)) as mp:
            def __mkSubVol(name, mode, uid, gid):
                cls._createSubVol(mp.mountpoint, name)
                dirpath = os.path.join(mp.mountpoint, name)
                os.chown(dirpath, uid, gid)
                os.chmod(dirpath, mode)

            def __mkDir(name, mode, uid, gid):
                dirpath = os.path.join(mp.mountpoint, name)
                os.mkdir(dirpath)
                os.chown(dirpath, uid, gid)
                os.chmod(dirpath, mode)

            path, rootName, mode, uid, gid = cls._rootSubVol()
            __mkSubVol(rootName, mode, uid, gid)

            for path, name, mode, uid, gid in cls._homeSubVols():
                __mkSubVol(name, mode, uid, gid)
                __mkDir(rootName + path, mode, uid, gid)

            __mkDir(rootName + Util.varDir, *Util.varDirModeuidGid)
            for path, name, mode, uid, gid in cls._varSubVols():
                __mkSubVol(name, mode, uid, gid)
                __mkDir(rootName + path, mode, uid, gid)

            __mkSubVol("@snapshots", 0o40700, 0, 0)

    @classmethod
    def getSnapshotNameFromSubVolPath(cls, subvol):
        m = re.fullmatch("/@snapshots/([^/]+)/", subvol)
        return m.group(1)

    @classmethod
    def getParamsForMountWithoutSnapshot(self):
        ret = []
        for path, name, mode, uid, gid in self._allSubVols():
            ret.append((path, mode, uid, gid, ["subvol=/%s" % (name)]))
        return ret

    @staticmethod
    def proxy(func):
        if isinstance(func, property):
            def f_get(self):
                return getattr(self._snapshot, func.fget.__name__)
            f_get.__name__ = func.fget.__name__
            return property(f_get)
        else:
            def f(self, *args):
                return getattr(self._snapshot, func.__name__)(*args)
            return f

    def __init__(self, mntDir, snapshot=None):
        self._mntDir = mntDir
        self._snapshotName = snapshot

    @property
    def snapshot(self):
        return self._snapshotName

    def get_snapshot_list(self):
        subVolList = self._getSubVolList()
        ret = []
        for snapshotName in self._subVolList2SnapshotNameList(subVolList):
            if all([x in subVolList for x in self._snapshotName2SnapshotFullNameList(snapshotName)]):
                ret.append(snapshotName)
        return ret

    def create_snapshot(self, snapshot_name):
        # open file check
        pass

        # mtime check
        pass

        # /var/tmp should be empty
        pass

        for path, name, mode, uid, gid in self._allSubVols():
            if name not in self._subVolNamesExcludedFromSnapshoting():
                self._createSnapshotSubVol(self._mntDir, name, self._getSnapshotFullName(snapshot_name, name))
            else:
                self._createSubVol(self._mntDir, name)
                dirpath = os.path.join(self._mntDir, name)
                os.chown(dirpath, uid, gid)
                os.chmod(dirpath, mode)

    def remove_snapshot(self, snapshot_name):
        self._recursiveDeleteSubVols("@snapshots/%s" % (snapshot_name))

    def sync_from_snapshot(self, snapshot_name, home=False, var=False):
        subVolList = self._getSubVolList()
        if not all([x in subVolList for x in self._snapshotName2SnapshotFullNameList(snapshot_name)]):
            raise Exception("")

        # FIXME: rsync back
        assert False

        # FIXME: dangerous
        if home:
            assert False

        # FIXME: dangerous
        if var:
            # contents in self._subVolNamesExcludedFromSnapshoting() are not important, they will be lost
            assert False

    def check(self, auto_fix, error_callback):
        nameList = []
        if True:
            for path, name, mode, uid, gid in self._allSubVols():
                nameList.append(name)
            nameList.append("@snapshots")

        # check existence
        svList = self._getSubVolList(self._mntDir)
        for sv in nameList:
            try:
                svList.remove(sv)
            except ValueError:
                # no way to auto fix
                error_callback(errors.CheckCode.TRIVIAL, "Sub-volume \"%s\" does not exist." % (sv))

        # check snapshots
        for snapshotName in self._subVolList2SnapshotNameList(svList):
            for sv in self._snapshotName2SnapshotFullNameList(snapshotName):
                try:
                    svList.remove(sv)
                except ValueError:
                    # no way to auto fix
                    error_callback(errors.CheckCode.TRIVIAL, "Sub-volume \"%s\" does not exist when it should be." % (sv))

        # check redundancy
        for sv in svList:
            # too dangerous to auto fix
            error_callback(errors.CheckCode.TRIVIAL, "Redundant sub-volume \"%s\"." % (sv))

    def _subVolList2SnapshotNameList(self, subVolList):
        ret = []
        for sv in subVolList:
            m = re.fullmatch("@snapshots/([^/]+)/", sv)
            if m is not None:
                ret.append(m.group(1))
        return ret

    def _snapshotName2SnapshotFullNameList(self, snapshotName):
        ret = []
        for path, name, mode, uid, gid in self._allSubVols():
            ret.append(self._getSnapshotFullName(snapshotName, name))
        return ret

    @staticmethod
    def _getSnapshotFullName(snapshotName, name):
        return "@snapshots/%s/%s" % (snapshotName, name)

    @classmethod
    def _allSubVols(cls):
        return [cls._rootSubVol()] + cls._homeSubVols() + cls._varSubVols()

    @staticmethod
    def _rootSubVol():
        return (Util.rootfsDir, "@", *Util.rootfsDirModeUidGid)

    @staticmethod
    def _homeSubVols():
        return [
            ("/root", "@root", 0o40700, 0, 0),
            ("/home", "@home", 0o40755, 0, 0),
        ]

    @staticmethod
    def _varSubVols():
        return [
            ("/var/cache", "@var_cache", 0o40755, 0, 0),
            ("/var/db",    "@var_db",    0o40755, 0, 0),
            ("/var/games", "@var_games", 0o40755, 0, 0),     # FIXME
            ("/var/lib",   "@var_lib",   0o40755, 0, 0),
            ("/var/log",   "@var_log",   0o40755, 0, 0),
            ("/var/spool", "@var_spool", 0o40755, 0, 0),
            ("/var/tmp",   "@var_tmp",   0o41777, 0, 0),
            ("/var/www",   "@var_www",   0o40755, 0, 0),     # FIXME
        ]

    @staticmethod
    def _subVolNamesExcludedFromSnapshoting():
        return [
            "@var_log",
            "@var_tmp",
        ]

    @staticmethod
    @abc.abstractmethod
    def _createSubVol(mntDir, subVolPath):
        pass

    @staticmethod
    @abc.abstractmethod
    def _createSnapshotSubVol(mntDir, srcSubVolPath, subVolPath):
        pass

    @staticmethod
    @abc.abstractmethod
    def _recursiveDeleteSubVols(mntDir, subVolPath):
        pass

    @staticmethod
    @abc.abstractmethod
    def _getSubVolList(mntDir):
        pass


class SubVolsBtrfs(SubVols):

    @classmethod
    def mntArgsDictSetSnapshot(cls, storageLayoutName, mount_dir, mnt_args_dict):
        ret = Util.mntGetSubVolPath(mount_dir)
        if ret is None:
            raise errors.StorageLayoutParseError(storageLayoutName, "sub-volume not used")
        if not ret.startswith("/@"):
            raise errors.StorageLayoutParseError(storageLayoutName, "sub-volume \"%s\" is invalid" % (ret))
        if len(ret) > 2:
            mnt_args_dict["snapshot"] = cls.getSnapshotNameFromSubVolPath(ret)

    @classmethod
    def mntParamsMergeMntArgSnapshot(cls, mntParams, mntArgsDict):
        snapshotName = mntArgsDict.pop("snapshot", None)
        if snapshotName is None:
            return

        for p in mntParams:
            for i in range(0, len(p.mnt_opt_list)):
                if p.mnt_opt_list[i].startswith("subvol=/"):
                    name = p.mnt_opt_list[len("subvol=/"):]
                    name = cls._getSnapshotFullName(snapshotName, name)
                    p.mnt_opt_list[i] = "subvol=/%s" % (name)

    @staticmethod
    def _createSubVol(mntDir, subVolPath):
        Util.cmdCall("btrfs", "subvolume", "create", os.path.join(mntDir, subVolPath))

    @staticmethod
    def _createSnapshotSubVol(mntDir, srcSubVolPath, subVolPath):
        Util.cmdCall("btrfs", "subvolume", "snapshot", os.path.join(mntDir, srcSubVolPath), os.path.join(mntDir, subVolPath))

    @staticmethod
    def _recursiveDeleteSubVols(mntDir, subVolPath):
        Util.cmdCall("btrfs", "subvolume", "delete", os.path.join(mntDir, subVolPath))

    @staticmethod
    def _getSubVolList(mntDir):
        ret = []
        out = Util.cmdCall("btrfs", "subvolume", "list", mntDir)
        for m in re.finditer("path (\\S+)", out, re.M):
            ret.append(m.group(1))
        return ret


# class SubVolsBcachefs(SubVols):

#     @classmethod
#     def mntArgsDictSetSnapshot(cls, storageLayoutName, mount_dir, mnt_args_dict):
#         assert False

#     @staticmethod
#     def _createSubVol(mntDir, subVolPath):
#         Util.cmdCall("bcachefs", "subvolume", "create", os.path.join(mntDir, subVolPath))

#     @staticmethod
#     def _createSnapshotSubVol(mntDir, srcSubVolPath, subVolPath):
#         Util.cmdCall("bcachefs", "subvolume", "snapshot", os.path.join(mntDir, srcSubVolPath), os.path.join(mntDir, subVolPath))

#     @staticmethod
#     def _deleteSubVol(mntDir, subVolPath):
#         Util.cmdCall("bcachefs", "subvolume", "delete", os.path.join(mntDir, subVolPath))

#     @staticmethod
#     def _getSubVolList(mntDir):
#         out = Util.cmdCall("bcachefs", "subvolume", "list", mntDir)
#         # FIXME: parse out
#         assert False


class Mount(abc.ABC):

    class MountEntry:

        def __init__(self, device, mountpoint, fstype, opts, real_dir_path):
            assert device is not None
            assert os.path.isabs(mountpoint)
            assert fstype is not None
            assert opts is not None
            assert real_dir_path is not None

            self._device = device
            self._mountpoint = mountpoint
            self._fstype = fstype
            self._opts = opts

            self._real_dir_path = real_dir_path

        @property
        def device(self):
            return self._device

        @property
        def mountpoint(self):
            return self._mountpoint

        @property
        def fstype(self):
            return self._fstype

        @property
        def opts(self):
            return self._opts

        @property
        def mnt_opt_list(self):
            return self.opts.split(",")

        @property
        def real_dir_path(self):
            return self._real_dir_path

        @property
        def real_opts(self):
            assert self._device is not None
            return PhysicalDiskMounts.find_entry_by_mount_point(self._real_dir_path).opts

        @property
        def real_mnt_opt_list(self):
            return self.real_opts.split(",")

    @staticmethod
    def proxy(func):
        if isinstance(func, property):
            def f_get(self):
                return getattr(self._mnt, func.fget.__name__)
            f_get.__name__ = func.fget.__name__
            return property(f_get)
        else:
            def f(self, *args):
                return getattr(self._mnt, func.__name__)(*args)
            return f

    @staticmethod
    @abc.abstractmethod
    def _assertMntParams(mntParams):
        pass

    def __init__(self, bIsMounted, mntDir, getMntParamsFunc, mntArgsDict):
        self._mntDir = mntDir
        self._getMntParamsFunc = getMntParamsFunc
        self._mntEntries = []

        # consume mntArgDict, do mount if neccessary, record mount entries
        for p in self._myGetMntParams(mntArgsDict):
            if p.mountpoint != "/":
                real_dir_path = os.path.join(self._mntDir, p.mountpoint[1:])
            else:
                real_dir_path = self._mntDir

            if not bIsMounted:
                if p.mountpoint != "/":
                    if not os.path.exists(real_dir_path):
                        os.mkdir(real_dir_path)
                        os.chmod(real_dir_path, p.mnt_dir_mode)
                        os.chown(real_dir_path, p.mnt_dir_uid, p.mnt_dir_gid)
                    elif os.path.isdir(real_dir_path) and not os.path.islink(real_dir_path):
                        st = os.stat(real_dir_path)
                        if st.st_mode != p.mnt_dir_mode:
                            raise errors.StorageLayoutMountError("mount directory \"%s\" has invalid permission" % (real_dir_path))
                        if st.st_uid != p.mnt_dir_uid:
                            raise errors.StorageLayoutMountError("mount directory \"%s\" has invalid owner" % (real_dir_path))
                        if st.st_gid != p.mnt_dir_gid:
                            raise errors.StorageLayoutMountError("mount directory \"%s\" has invalid owner group" % (real_dir_path))
                    else:
                        raise errors.StorageLayoutMountError("mount directory \"%s\" is invalid" % (real_dir_path))
                if p.device is not None:
                    Util.cmdCall("mount", "-t", p.fstype, "-o", p.opts, p.device, real_dir_path)

            self._mntEntries.append(self.MountEntry(p.device, p.mountpoint, p.fstype, p.opts, real_dir_path))

    @property
    def mount_point(self):
        return self._mntDir

    def get_mount_commands(self, **kwargs):
        return self._myGetMntParams(kwargs.copy())

    def umount(self):
        for p in reversed(self._mntEntries):
            if p.device is not None:
                Util.cmdCall("umount", p.real_dir_path)

    def _myGetMntParams(self, mntArgsDict):
        mntParams = self._getMntParamsFunc(mntArgsDict)

        # check mntParams
        assert len(mntParams) > 0
        assert all([isinstance(x, MountCommand.Mount) for x in mntParams])
        assert mntParams[0].mountpoint == "/"
        self._assertMntParams(mntParams)

        # all items in mntArgDict should be consumed
        assert len(mntArgsDict) == 0

        return mntParams


class MountBios(Mount):

    @staticmethod
    def mntArgsDictSetReadOnly(storageLayoutName, mount_dir, mntArgsDict):
        if "ro" in PhysicalDiskMounts.find_entry_by_mount_point(mount_dir).mnt_opt_list:
            mntArgsDict["read_only"] = True

    @staticmethod
    def mntParamsMergeMntArgReadOnly(mntParams, mntArgsDict):
        if mntArgsDict.pop("read_only", False):
            mntParams[0].mnt_opt_list.append("ro")

    @staticmethod
    def _assertMntParams(mntParams):
        assert len(mntParams) == 1
        assert all(["ro" not in x.mnt_opt_list for x in mntParams])             # avoids conflict with mntArgsDict["read_only"]
        assert all(["rw" not in x.mnt_opt_list for x in mntParams])             # avoids conflict with mntArgsDict["read_only"]

    def __init__(self, bIsMounted, mntDir, getMntParamsFunc, mntArgsDict):
        self._readOnly = mntArgsDict.get("read_only", False)
        super().__init__(bIsMounted, mntDir, getMntParamsFunc, mntArgsDict)

    def is_read_only(self):
        return self._readOnly

    def check_mount_write_mode(self, auto_fix=False, error_callback=None):
        if self._readOnly:
            error_callback(errors.CheckCode.TRIVIAL, "The whole file system is mounted read-only.")


class MountEfi(Mount):

    class RwController(RwController):

        def __init__(self, parent):
            self._parent = parent
            self._pEsp = self._parent._pEsp

        def is_writable(self):
            return "rw" in self._pEsp.real_mnt_opt_list

        def to_read_write(self):
            if not self._parent.is_read_only():
                if "rw" not in self._pEsp.real_mnt_opt_list:
                    Util.cmdCall("mount", self._pEsp.real_dir_path, "-o", "rw,remount")

        def to_read_only(self):
            if "rw" in self._pEsp.real_mnt_opt_list:
                Util.cmdCall("mount", self._pEsp.real_dir_path, "-o", "ro,remount")

    @staticmethod
    def mntArgsDictSetReadOnly(storageLayoutName, mount_dir, mntArgsDict):
        if "ro" in PhysicalDiskMounts.find_entry_by_mount_point(mount_dir).mnt_opt_list:
            mntArgsDict["read_only"] = True

    @staticmethod
    def mntParamsMergeMntArgReadOnly(mntParams, mntArgsDict):
        if mntArgsDict.pop("read_only", False):
            for p in mntParams:
                if p.mountpoint != Util.bootDir:
                    p.mnt_opt_list.append("ro")

    @staticmethod
    def _assertMntParams(mntParams):
        assert len(mntParams) >= 2

        # avoids conflict with mntArgsDict["read_only"]
        for p in mntParams:
            if p.mountpoint != Util.bootDir:
                assert "ro" not in p.mnt_opt_list
            assert "rw" not in p.mnt_opt_list

    def __init__(self, bIsMounted, mntDir, getMntParamsFunc, mntArgsDict):
        self._readOnly = mntArgsDict.get("read_only", False)
        super().__init__(bIsMounted, mntDir, getMntParamsFunc, mntArgsDict)
        self._pRootfs = self._findRootfsMountEntry()
        self._pEsp = self._findEspMountEntry()
        self._rwCtrl = self.RwController(self)

    def is_read_only(self):
        return self._readOnly

    def get_bootdir_rw_controller(self):
        return self._rwCtrl

    def mount_esp(self, parti):
        assert self._pEsp.device is None
        Util.cmdCall("mount", "-t", self._pEsp.fstype, "-o", self._pEsp.opts, parti, self._pEsp.real_dir_path)
        self._pEsp._device = parti

    def umount_esp(self, parti):
        assert parti == self._pEsp.device
        assert "rw" not in self._pEsp.mnt_opt_list
        Util.cmdCall("umount", self._pEsp.real_dir_path)
        self._pEsp._device = None

    def check_mount_write_mode(self, auto_fix=False, error_callback=None):
        if self._readOnly:
            error_callback(errors.CheckCode.TRIVIAL, "The whole file system is mounted read-only.")
        if self._rwCtrl.is_writable():
            if auto_fix:
                self._rwCtrl.to_read_only()
            else:
                error_callback(errors.CheckCode.TRIVIAL, "Boot directory should be mounted read-only.")

    def _findRootfsMountEntry(self):
        for p in self._mntEntries:
            if p.mountpoint == "/":
                return p
        assert False

    def _findEspMountEntry(self):
        for p in self._mntEntries:
            if p.mountpoint == Util.bootDir:
                return p
        assert False


class MountWindowsEfi(Mount):

    def __init__(self, bIsMounted, mntDir, getMntParamsFunc, mntArgsDict):
        self._readOnly = mntArgsDict.get("read_only", False)
        super().__init__(bIsMounted, mntDir, getMntParamsFunc, mntArgsDict)
        self._pRootfs = self._findRootfsMountEntry()
        self._pEsp = self._findEspMountEntry()

    def is_read_only(self):
        return self._readOnly

    def check_mount_write_mode(self, auto_fix=False, error_callback=None):
        if self._readOnly:
            error_callback(errors.CheckCode.TRIVIAL, "The whole file system is mounted read-only.")
        if self._rwCtrl.is_writable():
            if auto_fix:
                self._rwCtrl.to_read_only()
            else:
                error_callback(errors.CheckCode.TRIVIAL, "Boot directory should be mounted read-only.")

    def _findRootfsMountEntry(self):
        for p in self._mntEntries:
            if p.mountpoint == "/":
                return p
        assert False

    def _findEspMountEntry(self):
        for p in self._mntEntries:
            if p.mountpoint == Util.bootDir:
                return p
        assert False


class HandyMd:

    @staticmethod
    def checkAndAddDisks(md, diskList, fsType):
        if len(diskList) == 0:
            raise errors.StorageLayoutCreateError(errors.NO_DISK_WHEN_CREATE)
        for disk in diskList:
            if not Util.isHarddiskClean(disk):
                raise errors.StorageLayoutCreateError(errors.DISK_NOT_CLEAN(disk))
        for disk in diskList:
            md.add_disk(disk, fsType)

    @staticmethod
    def checkExtraDisks(storageLayoutName, diskList, origDiskList):
        d = list(set(diskList) - set(origDiskList))
        if len(d) > 0:
            raise errors.StorageLayoutParseError(storageLayoutName, "extra disk \"%s\" needed" % (d[0]))

    @staticmethod
    def checkAndGetBootDiskFromBootDev(storageLayoutName, bootDev, diskList):
        HandyUtil._mcCheckHddOrDiskList(storageLayoutName, diskList)
        espParti = HandyUtil._mcCheckAndGetEspParti(storageLayoutName, diskList, mustHave=True)
        if espParti != bootDev:
            raise errors.StorageLayoutParseError(storageLayoutName, errors.BOOT_DEV_MUST_BE(espParti))
        return PartiUtil.partiToDisk(espParti)

    @staticmethod
    def checkAndGetBootDiskAndBootDev(storageLayoutName, diskList):
        HandyUtil._mcCheckHddOrDiskList(storageLayoutName, diskList)
        espParti = HandyUtil._mcCheckAndGetEspParti(storageLayoutName, diskList)
        return (PartiUtil.partiToDisk(espParti) if espParti is not None else None, espParti)


class HandyCg:

    @staticmethod
    def checkAndAddDisks(cg, ssdList, hddList, fsType):
        ssd, hddList = HandyCg.checkAndGetSsdAndHddList(ssdList, hddList)

        # ensure disks are clean
        if ssd is not None:
            if not Util.isHarddiskClean(ssd):
                raise errors.StorageLayoutCreateError(errors.DISK_NOT_CLEAN(ssd))
        for hdd in hddList:
            if not Util.isHarddiskClean(hdd):
                raise errors.StorageLayoutCreateError(errors.DISK_NOT_CLEAN(hdd))

        # add ssd first so that minimal boot disk change is need
        if ssd is not None:
            cg.add_ssd(ssd, fsType)
        for hdd in hddList:
            cg.add_hdd(hdd, fsType)

    @staticmethod
    def checkAndGetSsdAndHddList(ssdList, hddList):
        if len(ssdList) == 0:
            ssd = None
        elif len(ssdList) == 1:
            ssd = ssdList[0]
        else:
            raise errors.StorageLayoutCreateError(errors.MULTIPLE_SSD)
        if len(hddList) == 0:
            raise errors.StorageLayoutCreateError(errors.NO_DISK_WHEN_CREATE)
        return (ssd, hddList)

    @staticmethod
    def checkAndGetSsdPartitions(storageLayoutName, ssd):
        if ssd is not None:
            ssdEspParti = PartiUtil.diskToParti(ssd, 1)
            ssdCacheParti = PartiUtil.diskToParti(ssd, 2)

            # ssdEspParti
            if not GptUtil.isEspPartition(ssdEspParti):
                raise errors.StorageLayoutParseError(storageLayoutName, errors.BOOT_DEV_IS_NOT_ESP)
            if Util.getBlkDevSize(ssdEspParti) != Util.getEspSize():
                raise errors.StorageLayoutParseError(storageLayoutName, errors.PARTITION_SIZE_INVALID(ssdEspParti))

            # ssdCacheParti
            if not PartiUtil.partiExists(ssdCacheParti):
                raise errors.StorageLayoutParseError(storageLayoutName, "SSD has no cache partition")

            # redundant partitions
            if PartiUtil.diskHasMoreParti(ssd, 2):
                raise errors.StorageLayoutParseError(storageLayoutName, errors.DISK_HAS_REDUNDANT_PARTITION(ssd))

            return ssdEspParti, ssdCacheParti
        else:
            return None, None

    @staticmethod
    def checkExtraDisks(storageLayoutName, ssd, hddList, origDiskList):
        if ssd is not None and ssd not in origDiskList:
            raise errors.StorageLayoutParseError(storageLayoutName, "extra disk \"%s\" needed" % (ssd))
        d = list(set(hddList) - set(origDiskList))
        if len(d) > 0:
            raise errors.StorageLayoutParseError(storageLayoutName, "extra disk \"%s\" needed" % (d[0]))

    @staticmethod
    def checkAndGetBootHddFromBootDev(storageLayoutName, bootDev, ssdEspParti, hddList):
        HandyUtil._mcCheckHddOrDiskList(storageLayoutName, hddList)

        if ssdEspParti is not None:
            if ssdEspParti != bootDev:
                raise errors.StorageLayoutParseError(storageLayoutName, errors.BOOT_DEV_MUST_BE(ssdEspParti))
            HandyCg._checkNoEspPartiInHddList(storageLayoutName, hddList)
            return None
        else:
            espParti = HandyUtil._mcCheckAndGetEspParti(storageLayoutName, hddList, mustHave=True)
            if espParti != bootDev:
                raise errors.StorageLayoutParseError(storageLayoutName, errors.BOOT_DEV_MUST_BE(bootDev))
            return PartiUtil.partiToDisk(espParti)

    @staticmethod
    def checkAndGetBootHddAndBootDev(storageLayoutName, ssdEspParti, hddList):
        HandyUtil._mcCheckHddOrDiskList(storageLayoutName, hddList)

        if ssdEspParti is not None:
            HandyCg._checkNoEspPartiInHddList(storageLayoutName, hddList)
            return (None, ssdEspParti)
        else:
            espParti = HandyUtil._mcCheckAndGetEspParti(storageLayoutName, hddList)
            return (PartiUtil.partiToDisk(espParti) if espParti is not None else None, espParti)

    @staticmethod
    def _checkNoEspPartiInHddList(storageLayoutName, hddList):
        for hdd in hddList:
            if GptUtil.isEspPartition(PartiUtil.diskToParti(hdd, 1)):
                raise errors.StorageLayoutParseError(storageLayoutName, "HDD \"%s\" should not have ESP partition" % (hdd))


class HandyBcache:

    @staticmethod
    def getSsdAndHddListFromBcacheDevPathList(storageLayoutName, bcacheDevPathList):
        cacheParti = None
        backingPartiList = []
        newBcacheDevPathList = []
        newBcacheDevList = []
        for bcacheDevPath in bcacheDevPathList:
            bcacheDev = BcacheUtil.getBcacheDevFromDevPath(bcacheDevPath)
            tlist = BcacheUtil.getSlaveDevPathList(bcacheDevPath)
            if len(tlist) == 0:
                assert False
            elif len(tlist) == 1:
                if len(backingPartiList) > 0:
                    if cacheParti is not None:
                        raise errors.StorageLayoutParseError(storageLayoutName, "%s(%s) has no cache device" % (tlist[0], bcacheDev))
                cacheParti = None
                backingPartiList.append(tlist[0])
                newBcacheDevPathList.append(bcacheDevPath)
                newBcacheDevList.append(bcacheDev)
            elif len(tlist) == 2:
                if len(backingPartiList) > 0:
                    if cacheParti is None:
                        raise errors.StorageLayoutParseError(storageLayoutName, "%s(%s) has no cache device" % (backingPartiList[-1], newBcacheDevList[-1]))
                    if cacheParti != tlist[0]:
                        raise errors.StorageLayoutParseError(storageLayoutName, "%s(%s) has a different cache device" % (tlist[1], bcacheDev))
                cacheParti = tlist[0]
                backingPartiList.append(tlist[1])
                newBcacheDevPathList.append(bcacheDevPath)
                newBcacheDevList.append(bcacheDev)
            else:
                raise errors.StorageLayoutParseError(storageLayoutName, "%s(%s) has multiple cache devices" % (tlist[-1], bcacheDev))

        if cacheParti is None:
            ssd = None
        else:
            ssd = PartiUtil.partiToDisk(cacheParti)
        hddList = [PartiUtil.partiToDisk(x) for x in backingPartiList]

        return (ssd, hddList)


class DisksChecker:

    def __init__(self, disk_list):
        assert len(disk_list) > 0
        self._hddList = disk_list

    def dispose(self):
        pass

    def check_logical_sector_size(self, auto_fix, error_callback):
        for hdd in self._hddList:
            dev, disk = self._partedGetDevAndDisk(hdd)
            if disk.type == "msdos":
                if dev.sectorSize != 512:
                    error_callback(errors.CheckCode.TRIVIAL, "%s uses MBR partition table, its logical sector size (%d) should be 512" % (hdd, dev.sectorSize))
            elif disk.type == "gpt":
                if dev.physicalSectorSize in [512, 4096]:
                    if dev.sectorSize != dev.physicalSectorSize:
                        error_callback(errors.CheckCode.TRIVIAL, "%s has different physical sector size (%d) and logical sector size (%d)" % (hdd, dev.physicalSectorSize, dev.sectorSize))
                else:
                    if dev.sectorSize not in [512, 4096]:
                        error_callback(errors.CheckCode.TRIVIAL, "%s has inapporiate logical sector size (%d)" % (hdd, dev.sectorSize))

    def check_boot_sector(self, auto_fix, error_callback):
        # struct mbr_partition_record {
        #     uint8_t  boot_indicator;
        #     uint8_t  start_head;
        #     uint8_t  start_sector;
        #     uint8_t  start_track;
        #     uint8_t  os_type;
        #     uint8_t  end_head;
        #     uint8_t  end_sector;
        #     uint8_t  end_track;
        #     uint32_t starting_lba;
        #     uint32_t size_in_lba;
        # };
        mbrPartitionRecordFmt = "8BII"
        assert struct.calcsize(mbrPartitionRecordFmt) == 16

        # struct mbr_header {
        #     uint8_t                     boot_code[440];
        #     uint32_t                    unique_mbr_signature;
        #     uint16_t                    unknown;
        #     struct mbr_partition_record partition_record[4];
        #     uint16_t                    signature;
        # };
        mbrHeaderFmt = "440sIH%dsH" % (struct.calcsize(mbrPartitionRecordFmt) * 4)
        assert struct.calcsize(mbrHeaderFmt) == 512

        for hdd in self._hddList:
            dev, disk = self._partedGetDevAndDisk(hdd)
            if disk.type == "msdos":
                pass
            elif disk.type == "gpt":
                # FIXME: we can't use self._partedReadSectors() since it returns str, not bytes, what a bug!
                # mbrHeader = struct.unpack(mbrHeaderFmt, self._partedReadSectors(dev, 0, 1)[:struct.calcsize(mbrHeaderFmt)])

                with open(hdd, "rb") as f:
                    # read Protective MBR header
                    buf = f.read(struct.calcsize(mbrHeaderFmt))
                    mbrHeader = struct.unpack(mbrHeaderFmt, buf)

                    # check Protective MBR header
                    if not Util.isBufferAllZero(mbrHeader[0]):
                        error_callback(errors.CheckCode.TRIVIAL, "Protective MBR Boot Code should be empty for %s" % (hdd))
                        continue
                    if mbrHeader[1] != 0:
                        error_callback(errors.CheckCode.TRIVIAL, "Protective MBR Disk Signature should be zero for %s" % (hdd))
                        continue
                    if mbrHeader[2] != 0:
                        error_callback(errors.CheckCode.TRIVIAL, "reserved area in Protective MBR should be zero for %s" % (hdd))
                        continue
                    if mbrHeader[4] != 0xAA55:
                        error_callback(errors.CheckCode.TRIVIAL, "signature in Protective MBR should be 0xAA55 for %s" % (hdd))
                        continue

                    # check Protective MBR Partition Record
                    pRec = struct.unpack_from(mbrPartitionRecordFmt, mbrHeader[3], 0)
                    if pRec[4] != 0xEE:
                        error_callback(errors.CheckCode.TRIVIAL, "the first Partition Record should be Protective MBR Partition Record (OS Type == 0xEE) for %s" % (hdd))
                        continue
                    if pRec[0] != 0:
                        error_callback(errors.CheckCode.TRIVIAL, "Boot Indicator in Protective MBR Partition Record should be zero for %s" % (hdd))
                        continue

                    # other Partition Record should be filled with zero
                    if not Util.isBufferAllZero(mbrHeader[struct.calcsize(mbrPartitionRecordFmt):]):
                        error_callback(errors.CheckCode.TRIVIAL, "all Partition Records should be filled with zero for %s" % (hdd))
                        continue

                    # read to gpt header
                    buf = f.read(dev.sectorSize - struct.calcsize(mbrHeaderFmt))
                    if not Util.isBufferAllZero(buf):
                        error_callback(errors.CheckCode.TRIVIAL, "space between Protective MBR and GPT header should be filled with zero for %s" % (hdd))
                        continue

                    # ghnt and check primary and backup GPT header
                    pass

    def check_partition_type(self, partition_type, auto_fix, error_callback):
        for hdd in self._hddList:
            dev, disk = self._partedGetDevAndDisk(hdd)
            if disk.type != partition_type:
                error_callback(errors.CheckCode.TRIVIAL, "Inappopriate partition type for %s" % (hdd))

    def check_partition_uuid(self, auto_fix, error_callback):
        for hdd in self._hddList:
            partUuidDict = dict()
            for i in range(1, sys.maxsize):
                partiDevPath = PartiUtil.diskToParti(hdd, i)
                if not PartiUtil.partiExists(partiDevPath):
                    break
                partUuid = Util.getBlkDevPartUuid(partiDevPath)
                if partUuid == "":
                    error_callback(errors.CheckCode.TRIVIAL, "%s has no partition UUID" % (partiDevPath))
                    continue
                if partUuid in partUuidDict:
                    error_callback(errors.CheckCode.TRIVIAL, "%s and %s has same partition UUID" % (partUuidDict[partUuid], partiDevPath))
                    continue
                partUuidDict[partUuid] = partiDevPath

    def _partedGetDevAndDisk(self, devPath):
        partedDev = parted.getDevice(devPath)
        return (partedDev, parted.newDisk(partedDev))

    def _partedReadSectors(self, partedDev, startSector, sectorCount):
        partedDev.open()
        try:
            return partedDev.read(startSector, sectorCount)
        finally:
            partedDev.close()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.dispose()


class HandyUtil:

    @staticmethod
    def getStorageLayoutName(layoutClass):
        fn = sys.modules.get(layoutClass.__module__).__file__
        fn = os.path.basename(fn).replace(".py", "")
        return Util.modName2layoutName(fn)

    @staticmethod
    def checkMntOptList(mntOptList):
        tset = set()
        for mo in mntOptList:
            idx = mo.find("=")
            if idx >= 0:
                mo2 = mo[0:idx]
            else:
                mo2 = mo
            if mo2 in tset:
                raise errors.StorageLayoutMountError("duplicate mount option \"%s\"" % (mo))
            tset.add(mo)

    @staticmethod
    def checkAndGetHdd(diskList):
        if len(diskList) == 0:
            raise errors.StorageLayoutCreateError(errors.NO_DISK_WHEN_CREATE)
        if len(diskList) > 1:
            raise errors.StorageLayoutCreateError(errors.MULTIPLE_DISKS_WHEN_CREATE)
        if not Util.isHarddiskClean(diskList[0]):
            raise errors.StorageLayoutCreateError(errors.DISK_NOT_CLEAN(diskList[0]))
        return diskList[0]

    @staticmethod
    def swapFileDetectAndNew(storageLayoutName, rootfs_mount_dir):
        fullfn = rootfs_mount_dir.rstrip("/") + Util.swapFilepath
        if os.path.exists(fullfn):
            if not Util.cmdCallTestSuccess("swaplabel", fullfn):
                raise errors.StorageLayoutParseError(storageLayoutName, errors.SWAP_DEV_HAS_INVALID_FS_FLAG(fullfn))
            return SwapFile(True)
        else:
            return SwapFile(False)

    @staticmethod
    def _mcCheckHddOrDiskList(storageLayoutName, diskOrHddList):
        for disk in diskOrHddList:
            if Util.getBlkDevPartitionTableType(disk) != Util.diskPartTableGpt:
                raise errors.StorageLayoutParseError(storageLayoutName, errors.PARTITION_TYPE_SHOULD_BE(disk, Util.diskPartTableGpt))

            # esp partition
            espParti = PartiUtil.diskToParti(disk, 1)
            if Util.getBlkDevFsType(espParti) != Util.fsTypeFat:
                raise errors.StorageLayoutParseError(storageLayoutName, errors.PARTITION_TYPE_SHOULD_BE(espParti, Util.fsTypeFat))
            if Util.getBlkDevSize(espParti) != Util.getEspSize():
                raise errors.StorageLayoutParseError(storageLayoutName, errors.PARTITION_SIZE_INVALID(espParti))

            # data partition
            if not PartiUtil.diskHasParti(disk, 2):
                raise errors.StorageLayoutParseError(storageLayoutName, "HDD \"%s\" has no data partition" % (disk))

            # redundant partitions
            if PartiUtil.diskHasMoreParti(disk, 2):
                raise errors.StorageLayoutParseError(storageLayoutName, errors.DISK_HAS_REDUNDANT_PARTITION(disk))

    @staticmethod
    def _mcCheckAndGetEspParti(storageLayoutName, diskOrHddList, mustHave=False):
        espPartiList = []
        for disk in diskOrHddList:
            parti = PartiUtil.diskToParti(disk, 1)
            if GptUtil.isEspPartition(parti):
                espPartiList.append(parti)
        if len(espPartiList) == 0:
            if mustHave:
                raise errors.StorageLayoutParseError(storageLayoutName, "no ESP partitions found")
            else:
                return None
        elif len(espPartiList) == 1:
            return espPartiList[0]
        else:
            raise errors.StorageLayoutParseError(storageLayoutName, "multiple ESP partitions found")
