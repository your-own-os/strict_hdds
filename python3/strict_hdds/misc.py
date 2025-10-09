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


class BootDirWriter:

    def __init__(self, layout):
        if layout is not None and layout.name in ["efi-ext4", "efi-btrfs", "efi-bcache-btrfs", "efi-bcachefs", "efi-msr-ntfs"]:
            self._ctrl = layout.get_bootdir_rw_controller()
            self._origIsWritable = None
        else:
            self._ctrl = None

    def __enter__(self):
        if self._ctrl is not None:
            self._origIsWritable = self._ctrl.is_writable()
            if not self._origIsWritable:
                self._ctrl.to_read_write()
        return self

    def __exit__(self, type, value, traceback):
        if self._ctrl is not None:
            if not self._origIsWritable:
                self._ctrl.to_read_only()
