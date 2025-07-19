# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import shutil
from dataclasses import replace
from io import StringIO
from pathlib import Path
from stat import S_IFLNK, S_IFDIR, S_IFREG, S_IMODE, S_ISLNK, S_ISDIR
from textwrap import dedent
from typing import Sequence

import pytest

from rumar import Rumar, make_profile_to_settings_from_toml_text, Rath, iter_all_files, iter_matching_files, is_dir_matching_top_dirs, derive_relative_p

_path_to_lstat_ = {}


class Rather(Rath):
    BASE_PATH = None

    def __init__(self, *args,
                 lstat_cache: dict[Path, os.stat_result],
                 mtime: float = None,
                 content: str = None,
                 chmod: int = 0o644,
                 islnk: bool = False,
                 isdir: bool = False):
        if self.BASE_PATH:
            args = [self.BASE_PATH, Path(*args).relative_to('/')]
        super().__init__(*args, lstat_cache=lstat_cache if lstat_cache is not None else _path_to_lstat_)
        self._mtime = mtime or 0
        content = content or f"{self}\n"
        self._content_io = StringIO(content)
        self._st_size = len(content.encode('utf-8'))
        if islnk:
            filetype = S_IFLNK
        elif isdir:
            filetype = S_IFDIR
        else:
            filetype = S_IFREG
        self._mode = chmod | filetype

    def lstat(self):
        return os.stat_result((
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

    def open(self, mode='r', *args, **kwargs):
        if 'r' in mode:
            return self._content_io
        else:
            raise ValueError(f"Unsupported mode: {mode}")

    def make(self):
        lstat = self.lstat()
        dir_rath = self if S_ISDIR(lstat.st_mode) else self.parent
        dir_rath.mkdir(parents=True, exist_ok=True)
        with open(self, 'w') as f:
            f.write(self._content_io.read())
        self.chmod(self._mode)
        os.utime(self, (lstat.st_atime, lstat.st_mtime))
        return self

    def asrath(self):
        return Rath(self, lstat_cache=self.lstat_cache)


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


@pytest.fixture(scope='class')
def set_up_rumar():
    BASE = Path('/tmp/rumar')
    Rather.BASE_PATH = BASE
    profile = 'profileA'
    toml = dedent(f"""\
    version = 2
    db_path = ':memory:'
    backup_base_dir = '{BASE}/backup-base-dir'
    [{profile}]
    source_dir = '{BASE}/{profile}'
    """)
    profile_to_settings = make_profile_to_settings_from_toml_text(toml)
    rumar = Rumar(profile_to_settings)
    rumar._at_beginning(profile)
    fs_paths = [
        f"/{profile}/file01.txt",
        f"/{profile}/file02.txt",
        f"/{profile}/file03.csv",
        f"/{profile}/A/file04.txt",
        f"/{profile}/A/file05.txt",
        f"/{profile}/A/file06.csv",
        f"/{profile}/B/file07.txt",
        f"/{profile}/B/file08.txt",
        f"/{profile}/B/file09.csv",
        f"/{profile}/AA/file10.txt",
        f"/{profile}/AA/file11.txt",
        f"/{profile}/AA/file12.csv",
        f"/{profile}/A/A-A/file13.txt",
        f"/{profile}/A/A-A/file14.txt",
        f"/{profile}/A/A-A/file15.csv",
        f"/{profile}/A/A-B/file16.txt",
        f"/{profile}/A/A-B/file17.txt",
        f"/{profile}/A/A-B/file18.csv",
    ]
    rathers = [
        Rather(fs_path, lstat_cache=rumar.lstat_cache, mtime=i * 60).make()
        for i, fs_path in enumerate(fs_paths, start=1)
    ]
    d = dict(
        profile=profile,
        profile_to_settings=profile_to_settings,
        rumar=rumar,
        rathers=rathers,
    )
    yield d
    if BASE.exists():
        shutil.rmtree(BASE / profile)
    Rather.BASE_PATH = None
    _path_to_lstat_.clear()


class TestRumarCore:

    def test_001_fs_iter_all_files(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        rumar = d['rumar']
        rathers: list[Rather] = d['rathers']
        expected = [r.asrath() for r in sorted(rathers)]
        top_dir = Rather(f"/{profile}", lstat_cache=rumar.lstat_cache)
        actual = sorted(iter_all_files(top_dir))
        assert eq_list(actual, expected)

    def test_inc_no_inc_or_exc(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: update local settings dict, not in rumar
                           included_files_as_glob=['*.csv'],
                           excluded_files_as_glob=['*1.*'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(p, lstat_cache=rumar.lstat_cache)
        actual = [
            is_dir_matching_top_dirs(R(f"/{profile}"), '/', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A"), '/A', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/AA"), '/AA', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/B"), '/B', settings),
        ]
        expected = [
            True,
            True,
            True,
            True,
        ]
        assert actual == expected

    def test_is_dir_matching_top_dirs__inc_single(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           included_top_dirs=['AA'],
                           included_files_as_glob=['*.csv'],
                           excluded_files_as_glob=['*1.*'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(p, lstat_cache=rumar.lstat_cache)
        actual = [
            is_dir_matching_top_dirs(R(f"/{profile}"), '/', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A"), '/A', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/AA"), '/AA', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/B"), '/B', settings),
        ]
        expected = [
            True,
            False,
            True,
            False,
        ]
        assert actual == expected

    def test_is_dir_matching_top_dirs__exc_several(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           excluded_top_dirs=['A', 'B'],
                           included_files_as_glob=['*.csv'],
                           excluded_files_as_glob=['*1.*'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(p, lstat_cache=rumar.lstat_cache)
        actual = [
            is_dir_matching_top_dirs(R(f"/{profile}"), '/', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A"), '/A', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/AA"), '/AA', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/B"), '/B', settings),
        ]
        expected = [
            True,
            False,
            True,
            False,
        ]
        assert actual == expected

    def test_is_dir_matching_top_dirs__exc_mulit_level(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           excluded_top_dirs=['B', 'A/A-A'],
                           included_files_as_glob=['*.csv'],
                           excluded_files_as_glob=['*1.*'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(p, lstat_cache=rumar.lstat_cache)
        actual = [
            is_dir_matching_top_dirs(R(f"/{profile}"), '/', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A"), '/A', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/AA"), '/AA', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/B"), '/B', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A/A-A"), '/A/A-A', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A/A-B"), '/A/A-B', settings),
        ]
        expected = [
            True,
            True,
            True,
            False,
            False,
            True,
        ]
        assert actual == expected

    def test_is_dir_matching_top_dirs__inc_and_exc_mulit_level(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           included_top_dirs=['A'],
                           excluded_top_dirs=['A/A-A'],
                           included_files_as_glob=['*.csv'],
                           excluded_files_as_glob=['*1.*'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(p, lstat_cache=rumar.lstat_cache)
        actual = [
            is_dir_matching_top_dirs(R(f"/{profile}"), '/', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A"), '/A', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/AA"), '/AA', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/B"), '/B', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A/A-A"), '/A/A-A', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A/A-B"), '/A/A-B', settings),
        ]
        expected = [
            True,
            True,
            False,
            False,
            False,
            True,
        ]
        assert actual == expected

    def test_is_dir_matching_top_dirs__inc__all_and_exc_single_lower_level(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           excluded_top_dirs=['A/A-A'],
                           included_files_as_glob=['*.csv'],
                           excluded_files_as_glob=['*1.*'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(p, lstat_cache=rumar.lstat_cache)
        actual = [
            is_dir_matching_top_dirs(R(f"/{profile}"), '/', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A"), '/A', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/AA"), '/AA', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/B"), '/B', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A/A-A"), '/A/A-A', settings),
            is_dir_matching_top_dirs(R(f"/{profile}/A/A-B"), '/A/A-B', settings),
        ]
        expected = [
            True,
            True,
            True,
            True,
            False,
            True,
        ]
        assert actual == expected

    def test_derive_relative_p_with_leading_slash(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        rumar = d['rumar']
        R = lambda p: Rather(p, lstat_cache=rumar.lstat_cache)
        top_rath = R(f"/{profile}")
        dir_rath = R(f"/{profile}/A")
        actual = derive_relative_p(dir_rath, top_rath, with_leading_slash=True)
        assert actual == '/A'

    def test_derive_relative_p_without_leading_slash(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        rumar = d['rumar']
        R = lambda p: Rather(p, lstat_cache=rumar.lstat_cache)
        top_rath = R(f"/{profile}")
        dir_rath = R(f"/{profile}/A/B/C/d.txt")
        actual = derive_relative_p(dir_rath, top_rath, with_leading_slash=False)
        assert actual == 'A/B/C/d.txt'

    def test_002_fs_test_iter_matching_files__inc_top_and_inc_glob(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,
                           included_top_dirs=['AA'],
                           included_files_as_glob=['*10.*'],
                           )
        rumar = d['rumar']
        expected = [Rather(f"/{profile}/AA/file10.txt", lstat_cache=rumar.lstat_cache).asrath(), ]
        top_path = Rather(f"/{profile}", lstat_cache=rumar.lstat_cache)
        actual = list(iter_matching_files(top_path, settings))
        assert eq_list(actual, expected)
