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
import enum


class MountCommand:

    class Mount:

        class FsType(enum.Enum):
            EXT4 = "ext4"
            BTRFS = "btrfs"
            BCACHEFS = "bcachefs"
            VFAT = "vfat"
            NTFS3 = "ntfs3"

        def __init__(self, dir_path, dir_mode, dir_uid, dir_gid, device, fstype, mnt_opt_list=[]):
            assert os.path.isabs(dir_path)
            assert dir_mode is not None
            assert isinstance(dir_uid, int)
            assert isinstance(dir_gid, int)
            assert device is not None
            assert isinstance(fstype, self.FsType)
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

    class Mkdir:

        def __init__(self, dir_path, dir_mode, dir_uid, dir_gid):
            assert os.path.isabs(dir_path)
            assert dir_mode is not None
            assert isinstance(dir_uid, int)
            assert isinstance(dir_gid, int)

            self.path = dir_path
            self.mode = dir_mode
            self.uid = dir_uid
            self.gid = dir_gid


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
