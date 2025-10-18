# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from _stat import S_IFLNK, S_IFDIR, S_IFREG, S_ISDIR, S_ISLNK
from io import BytesIO
from pathlib import Path, PurePath
from typing import Sequence

from rumar import Rath, compute_blake2b_checksum

_path_to_lstat_ = {}


class Rather(Rath):
    BASE_PATH = None
    NONE = object()

    def __init__(self, *args,
                 lstat_cache: dict[Path, os.stat_result],
                 mtime: float = 0,
                 content: str = '',
                 chmod: int = 0o644,
                 islnk: bool = False,
                 isdir: bool = False):
        if self.BASE_PATH:
            relative_args = p.parts[1:] if (p := Path(*args)).is_absolute() else args
            args = [self.BASE_PATH, *relative_args]
        super().__init__(*args, lstat_cache=lstat_cache if lstat_cache is not None else _path_to_lstat_)
        self._mtime = mtime
        self._content = f"{self}\n" if content == '' else content  # can be None, to produce None checksum for NULL blake2b
        self._st_size = len(self._content) if self._content else 0
        if islnk:
            filetype = S_IFLNK
        elif isdir:
            filetype = S_IFDIR
        else:
            filetype = S_IFREG
        self._mode = chmod | filetype
        self._checksum = None

    def _content_as_fileobj(self):
        return BytesIO(self._content.encode('utf-8')) if self._content else BytesIO()

    def lstat(self):
        if lstat := self.lstat_cache.get(self):
            return lstat
        else:
            lstat = os.stat_result((
                self._mode,  # st_mode
                0,  # st_ino
                0,  # st_dev
                1,  # st_nlink
                0,  # st_uid
                0,  # st_gid
                self._st_size,  # st_size
                self._mtime,  # st_atime
                self._mtime,  # st_mtime
                self._mtime  # st_ctime
            ))
            self.lstat_cache[self] = lstat
            return lstat

    def lstat_afresh(self):
        """Nothing to refresh"""
        return self.lstat()

    def open(self, mode='rb', *args, **kwargs):
        if 'r' in mode:
            if 'b' in mode:
                return self._content_as_fileobj()
            else:
                return self._content
        else:
            raise ValueError(f"Unsupported mode: {mode}")

    @property
    def content(self) -> str | None:
        return self._content

    @content.setter
    def content(self, value):
        self._content = value
        self._st_size = len(value) if value is not None else 0
        self._checksum = None  # checksum will be computed anew
        self.lstat_cache.pop(self, None)

    def make(self):
        lstat = self.lstat()
        dir_rath = self if S_ISDIR(lstat.st_mode) else self.parent
        dir_rath.mkdir(parents=True, exist_ok=True)
        with open(self, 'wb') as f:
            f.write(self._content.encode('utf-8') if self._content else b'')
        self.chmod(self._mode)
        os.utime(self, (lstat.st_atime, lstat.st_mtime))
        return self

    def as_rath(self):
        return Rath(self, lstat_cache=self.lstat_cache)

    def as_path(self):
        return Path(self)

    @property
    def checksum(self) -> bytes | None:
        if self._checksum is Rather.NONE:
            return None
        if self._checksum is None and self._content is not None:
            self._checksum = compute_blake2b_checksum(self._content_as_fileobj())
        return self._checksum

    @checksum.setter
    def checksum(self, value):
        # Tip: set it to Rather.NONE to get NULL blake2b even when content is not None
        self._checksum = value

    def clone(self):
        return Rather(*self.parts, lstat_cache=self.lstat_cache, mtime=self._mtime, content=self._content, chmod=self._mode, islnk=S_ISLNK(self._mode), isdir=S_ISDIR(self._mode))


def eq(path: Path, other: Path):
    """Compare two Path objects for equality\n
    - normalized case, same `os.path` type (e.g. posix)
    - same mtime
    - same size
    - same isdir, islnk - based on lstat(), i.e. follow_symlinks=False"""
    if not isinstance(path, Path) or not isinstance(other, Path):
        return False
    return (
            path == other and  # Path.__eq__: normalized case, same os.path type (e.g. posix)
            (p_l := path.lstat()).st_mtime == (o_l := other.lstat()).st_mtime and
            p_l.st_size == o_l.st_size and
            S_ISDIR(p_l.st_mode) == S_ISDIR(o_l.st_mode) and
            S_ISLNK(p_l.st_mode) == S_ISLNK(o_l.st_mode)
    )


def eq_list(path_list: list[Path], other_list: list[Path]):
    if len(path_list) != len(other_list):
        return False
    for path, other in zip(path_list, other_list):
        if not eq(path, other):
            return False
    return True


class PathEq:
    """A wrapper for Path that implements __eq__ and __hash__ as in eq()"""

    def __init__(self, path: Path):
        self.path = path

    def __eq__(self, other):
        if not isinstance(other, PathEq):
            return NotImplemented
        return eq(self.path, other.path)

    def __hash__(self):
        st = self.path.lstat()
        return hash((
            self.path,
            st.st_mtime,
            st.st_size,
            S_ISDIR(st.st_mode),
            S_ISLNK(st.st_mode)
        ))


def eq_seq_via_set(path_seq: Sequence[Path], other_seq: Sequence[Path]):
    """Compare two Path sequences for equality using `eq()`.\n
    Both will be converted to PathEq sets, i.e. can be in any order.
    """
    path_set = {PathEq(p) for p in path_seq}
    other_set = {PathEq(o) for o in other_seq}
    return path_set == other_set


def make_absolute_path(base_path: PurePath, relative_or_absolute: str | PurePath):
    path_cls = base_path.__class__  # to allow PureWindowsPath on Posix and vice versa, for testing purposes
    if (relative_or_absolute_path := path_cls(relative_or_absolute)).is_absolute():
        return relative_or_absolute_path
    else:
        return base_path / relative_or_absolute
