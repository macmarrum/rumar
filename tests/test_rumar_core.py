# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
import sys
import tarfile
import zipfile
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from textwrap import dedent

import pytest

from rumar import Rumar, make_profile_to_settings_from_toml_text, Rath, iter_all_files, derive_relative_psx, CreateReason, can_exclude_dir, can_include_dir, can_exclude_file, can_include_file, absolutopathlify, RumarDB, Settings
from stream_unzip import stream_unzip, ZIP_ZSTANDARD
from utils import Rather, eq_list

UTF8 = 'UTF-8'
password = '~!@#$%^&*()-= 123 qwe żółw'


def _can_match_dir(path, s, relative_psx):
    s.update(
        included_files=absolutopathlify(s.included_files, s.source_dir),
        excluded_files=absolutopathlify(s.excluded_files, s.source_dir),
        included_top_dirs=absolutopathlify(s.included_top_dirs, s.source_dir),
        excluded_top_dirs=absolutopathlify(s.excluded_top_dirs, s.source_dir),
    )
    if can_exclude_dir(path, s, relative_psx, base_path=s.source_dir):
        return 0
    return 1 if can_include_dir(path, s, relative_psx, base_path=s.source_dir) else 0


def _can_match_file(path, s, relative_psx):
    s.update(
        included_files=absolutopathlify(s.included_files, s.source_dir),
        excluded_files=absolutopathlify(s.excluded_files, s.source_dir),
        included_top_dirs=absolutopathlify(s.included_top_dirs, s.source_dir),
        excluded_top_dirs=absolutopathlify(s.excluded_top_dirs, s.source_dir),
    )
    if can_exclude_file(path, s, relative_psx, base_path=s.source_dir):
        return 0
    return 1 if can_include_file(path, s, relative_psx, base_path=s.source_dir) else 0


# for tests that need individual _set_up_rumar()
_tmp_path_factory: pytest.TempPathFactory = None


@pytest.fixture(scope='module')
def set_up_rumar(tmp_path_factory):
    global _tmp_path_factory
    _tmp_path_factory = tmp_path_factory
    d = _set_up_rumar()
    yield d
    _tear_down_rumar(d['rumar'], d['rumar']._rdb)


def _set_up_rumar():
    try:
        BASE = _tmp_path_factory.mktemp(basename='t', numbered=True)  # t0: module, t1..*: individual tests
    except AttributeError as e:
        if F"{e}" == "'NoneType' object has no attribute 'mktemp'":
            raise AttributeError("This test cannot be run in isolation; run it as part of the class, which ensures it's run after a test that uses set_up_rumar fixture")
    Rather.BASE_PATH = BASE
    profile = 'profileA'
    toml = dedent(f"""\
    version = 3
    db_path = ':memory:'
    backup_base_dir = '{BASE}/backup-base-dir'
    [{profile}]
    source_dir = '{BASE}/{profile}'
    """)
    profile_to_settings = make_profile_to_settings_from_toml_text(toml)
    s = profile_to_settings[profile]
    if BASE.exists():
        shutil.rmtree(BASE)
    if 'memory' not in s.db_path:
        BASE.mkdir(parents=True)
    rumar = Rumar(profile_to_settings)
    rumar._init_for_profile(profile)
    fs_paths = [
        f"/{profile}/file01.txt",
        f"/{profile}/file02.txt",
        f"/{profile}/file03.csv",
        f"/{profile}/A/file04.txt",
        f"/{profile}/A/file05.txt",
        f"/{profile}/A/file06.csv",
        f"/{profile}/A/A-A/file13.txt",
        f"/{profile}/A/A-A/file14.txt",
        f"/{profile}/A/A-A/file15.csv",
        f"/{profile}/A/A-B/file16.txt",
        f"/{profile}/A/A-B/file17.txt",
        f"/{profile}/A/A-B/file18.csv",
        f"/{profile}/B/file07.txt",
        f"/{profile}/B/file08.txt",
        f"/{profile}/B/file09.csv",
        f"/{profile}/AA/file10.txt",
        f"/{profile}/AA/file11.txt",
        f"/{profile}/AA/file12.csv",
    ]
    mtime = lambda i: datetime(2023, 1, 1, 0, i, 0).timestamp()
    rathers = [
        Rather(fs_path, lstat_cache=rumar.lstat_cache, mtime=mtime(i)).make()
        for i, fs_path in enumerate(fs_paths, start=1)
    ]
    raths = [r.as_rath() for r in rathers]
    d = dict(
        profile=profile,
        profile_to_settings=profile_to_settings,
        rumar=rumar,
        rathers=rathers,
        raths=raths,
    )
    return d


def _tear_down_rumar(rumar: Rumar, rumardb: RumarDB):
    rumar.lstat_cache.clear()
    rumardb.close_db()
    rumardb._profile_to_id.clear()
    rumardb._run_to_id.clear()
    rumardb._src_dir_to_id.clear()
    rumardb._source_to_id.clear()
    rumardb._bak_dir_to_id.clear()
    rumardb._backup_to_checksum.clear()


class TestDeriveRelativePsx:

    def test_derive_relative_psx__with_leading_slash(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        top_rath = R('A')
        dir_rath = R('A/B/C/c1.txt')
        expected = '/B/C/c1.txt'
        actual = derive_relative_psx(dir_rath, top_rath, with_leading_slash=True)
        assert actual == expected

    def test_derive_relative_psx__without_leading_slash(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        top_rath = R('A')
        dir_rath = R('A/B/C/c1.txt')
        expected = 'B/C/c1.txt'
        actual = derive_relative_psx(dir_rath, top_rath, with_leading_slash=False)
        assert actual == expected


class TestMatching:

    def test_can_match_dir__no_inc__no_exc(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': 1,
            'A': 1,
            'AA': 1,
            'B': 1,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    #######################################################################

    def test_can_match_dir__inc_top_dir_single__no_exc(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           included_top_dirs=['AA'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': 1,
            'A': 0,
            'AA': 1,
            'B': 0,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_dir__inc_full_stars_single__no_exc(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           included_files=['A/**'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': 1,
            'A': 1,
            'A/A-A': 1,
            'A/A-B': 1,
            'B': 0,
            'AA': 0,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_file__inc_full_stars_single__no_exc(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           included_files=['A/**'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            'file01.txt': 0,
            'file02.txt': 0,
            'file03.csv': 0,
            'A/file04.txt': 1,
            'A/file05.txt': 1,
            'A/file06.csv': 1,
            'A/A-A/file13.txt': 1,
            'A/A-A/file14.txt': 1,
            'A/A-A/file15.csv': 1,
            'A/A-B/file16.txt': 1,
            'A/A-B/file17.txt': 1,
            'A/A-B/file18.csv': 1,
            'B/file07.txt': 0,
            'B/file08.txt': 0,
            'B/file09.csv': 0,
            'AA/file10.txt': 0,
            'AA/file11.txt': 0,
            'AA/file12.csv': 0,
        }
        actual = {
            psx: _can_match_file(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    #######################################################################

    def test_can_match_dir__no_inc__exc_top_dir_several(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           excluded_top_dirs=['A', 'B'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': 1,
            'A': 0,
            'AA': 1,
            'B': 0,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_dir__no_inc__exc_full_stars_several(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           included_files=['A/**', 'B/**'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': 1,
            'A': 1,
            'A/A-A': 1,
            'A/A-B': 1,
            'B': 1,
            'AA': 0,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_file__no_inc__exc_full_stars_several(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           excluded_files=['A/**', 'B/**'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            'file01.txt': 1,
            'file02.txt': 1,
            'file03.csv': 1,
            'A/file04.txt': 0,
            'A/file05.txt': 0,
            'A/file06.csv': 0,
            'A/A-A/file13.txt': 0,
            'A/A-A/file14.txt': 0,
            'A/A-A/file15.csv': 0,
            'A/A-B/file16.txt': 0,
            'A/A-B/file17.txt': 0,
            'A/A-B/file18.csv': 0,
            'B/file07.txt': 0,
            'B/file08.txt': 0,
            'B/file09.csv': 0,
            'AA/file10.txt': 1,
            'AA/file11.txt': 1,
            'AA/file12.csv': 1,
        }
        actual = {
            psx: _can_match_file(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    #######################################################################

    def test_can_match_dir__no_inc__exc_top_dir_multi_level(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           excluded_top_dirs=['A/A-A', 'B'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': 1,
            'A': 1,
            'A/A-A': 0,
            'A/A-B': 1,
            'AA': 1,
            'B': 0,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_dir__no_inc__exc_full_stars_multi_level(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           included_files=['A/A-A/**', 'B/**'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': 1,
            'A': 1,
            'A/A-A': 1,
            'A/A-B': 0,
            'B': 1,
            'AA': 0,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_file__no_inc__exc_full_stars_multi_level(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           excluded_files=['A/A-A/**', 'B/**'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            'file01.txt': 1,
            'file02.txt': 1,
            'file03.csv': 1,
            'A/file04.txt': 1,
            'A/file05.txt': 1,
            'A/file06.csv': 1,
            'A/A-A/file13.txt': 0,
            'A/A-A/file14.txt': 0,
            'A/A-A/file15.csv': 0,
            'A/A-B/file16.txt': 1,
            'A/A-B/file17.txt': 1,
            'A/A-B/file18.csv': 1,
            'B/file07.txt': 0,
            'B/file08.txt': 0,
            'B/file09.csv': 0,
            'AA/file10.txt': 1,
            'AA/file11.txt': 1,
            'AA/file12.csv': 1,
        }
        actual = {
            psx: _can_match_file(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    #######################################################################

    def test_can_match_dir__inc_top_dir_single__exc_top_dir_subdir(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           included_top_dirs=['A'],
                           excluded_top_dirs=['A/A-A'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': 1,
            'A': 1,
            'A/A-A': 0,
            'A/A-B': 1,
            'AA': 0,
            'B': 0,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_dir__inc_full_stars_single__exc_full_stars_subdir(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           included_files=['A/**'],
                           excluded_files=['A/A-A/**'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': 1,
            'A': 1,
            'A/A-A': 0,
            'A/A-B': 1,
            'B': 0,
            'AA': 0,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_file__inc_full_stars_single__exc_full_stars_subdir(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           included_files=['A/**'],
                           excluded_files=['A/A-A/**'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            'file01.txt': 0,
            'file02.txt': 0,
            'file03.csv': 0,
            'A/file04.txt': 1,
            'A/file05.txt': 1,
            'A/file06.csv': 1,
            'A/A-A/file13.txt': 0,
            'A/A-A/file14.txt': 0,
            'A/A-A/file15.csv': 0,
            'A/A-B/file16.txt': 1,
            'A/A-B/file17.txt': 1,
            'A/A-B/file18.csv': 1,
            'B/file07.txt': 0,
            'B/file08.txt': 0,
            'B/file09.csv': 0,
            'AA/file10.txt': 0,
            'AA/file11.txt': 0,
            'AA/file12.csv': 0,
        }
        actual = {
            psx: _can_match_file(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    #######################################################################

    def test_can_match_dir__no_inc__exc_top_dir_single_subdir(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           excluded_top_dirs=['A/A-A'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': 1,
            'A': 1,
            'A/A-A': 0,
            'A/A-B': 1,
            'AA': 1,
            'B': 1,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_dir__no_inc__exc_full_stars_single_subdir(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           excluded_files=['A/A-A/**'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': 1,
            'A': 1,
            'A/A-A': 0,
            'A/A-B': 1,
            'B': 1,
            'AA': 1,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_file__no_inc__exc_full_stars_single_subdir(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           excluded_files=['A/A-A/**'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            'file01.txt': 1,
            'file02.txt': 1,
            'file03.csv': 1,
            'A/file04.txt': 1,
            'A/file05.txt': 1,
            'A/file06.csv': 1,
            'A/A-A/file13.txt': 0,
            'A/A-A/file14.txt': 0,
            'A/A-A/file15.csv': 0,
            'A/A-B/file16.txt': 1,
            'A/A-B/file17.txt': 1,
            'A/A-B/file18.csv': 1,
            'B/file07.txt': 1,
            'B/file08.txt': 1,
            'B/file09.csv': 1,
            'AA/file10.txt': 1,
            'AA/file11.txt': 1,
            'AA/file12.csv': 1,
        }
        actual = {
            psx: _can_match_file(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    #######################################################################

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_file__no_inc__exc_full_star_single_midlevel_dir(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           excluded_files=['A/*'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            'file01.txt': 1,
            'file02.txt': 1,
            'file03.csv': 1,
            'A/file04.txt': 0,
            'A/file05.txt': 0,
            'A/file06.csv': 0,
            'A/A-A/file13.txt': 1,
            'A/A-A/file14.txt': 1,
            'A/A-A/file15.csv': 1,
            'A/A-B/file16.txt': 1,
            'A/A-B/file17.txt': 1,
            'A/A-B/file18.csv': 1,
            'B/file07.txt': 1,
            'B/file08.txt': 1,
            'B/file09.csv': 1,
            'AA/file10.txt': 1,
            'AA/file11.txt': 1,
            'AA/file12.csv': 1,
        }
        actual = {
            psx: _can_match_file(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    @pytest.mark.skipif(sys.version_info < (3, 13), reason="full_match requires python 3.13 or higher")
    def test_can_match_file__inc_full_single_dir__exc_full_seq_in_same_dir__inc_dir_rx_single__inc_top_dir_single__inc_glob__exc_glob(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: local settings dict, not in rumar
                           included_files=['A/A-A/**'],
                           excluded_files=['A/A-A/????1[4-5]*'],
                           included_dirs_as_regex=[r'/A-B$'],
                           included_top_dirs=['AA'],
                           included_files_as_glob=['*.csv'],
                           excluded_files_as_glob=['*1.*'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            'file01.txt': 0,
            'file02.txt': 0,
            'file03.csv': 1,
            'A/file04.txt': 0,
            'A/file05.txt': 0,
            'A/file06.csv': 1,
            'A/A-A/file13.txt': 1,
            'A/A-A/file14.txt': 0,
            'A/A-A/file15.csv': 0,
            'A/A-B/file16.txt': 1,
            'A/A-B/file17.txt': 1,
            'A/A-B/file18.csv': 1,
            'B/file07.txt': 0,
            'B/file08.txt': 0,
            'B/file09.csv': 1,
            'AA/file10.txt': 1,
            'AA/file11.txt': 0,
            'AA/file12.csv': 1,
        }
        actual = {
            psx: _can_match_file(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected


class TestIterFiles:

    def test_001_fs_iter_all_files(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        rumar: Rumar = d['rumar']
        raths: list[Rath] = d['raths']
        expected = sorted(raths)
        top_dir = Rather(f"/{profile}", lstat_cache=rumar.lstat_cache)
        actual = sorted(iter_all_files(top_dir))
        assert eq_list(actual, expected)

    def test_002_fs_test_iter_matching_files__inc_top_and_inc_glob(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,
                           included_top_dirs=['AA'],
                           included_files_as_glob=['*/*1.*'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            'file01.txt': 1,
            'file02.txt': 0,
            'file03.csv': 0,
            'A/file04.txt': 0,
            'A/file05.txt': 0,
            'A/file06.csv': 0,
            'A/A-A/file13.txt': 0,
            'A/A-A/file14.txt': 0,
            'A/A-A/file15.csv': 0,
            'A/A-B/file16.txt': 0,
            'A/A-B/file17.txt': 0,
            'A/A-B/file18.csv': 0,
            'B/file07.txt': 0,
            'B/file08.txt': 0,
            'B/file09.csv': 0,
            'AA/file10.txt': 1,
            'AA/file11.txt': 1,
            'AA/file12.csv': 1,
        }
        actual = {
            psx: _can_match_file(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected


class TestCreateTar:

    def test_create_tar(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        rathers = d['rathers']
        rather = rathers[14]
        rumar = d['rumar']
        rumar._set_rath_and_friends(rather)
        actual_archive_path, actual_checksum = rumar._create(CreateReason.CREATE)
        assert actual_archive_path == rumar._archive_path
        assert actual_checksum == rather.checksum
        # print('\n##', f"archive_path: {archive_path}")
        self.compare_archive_contents([actual_archive_path], [rather], settings)

    @pytest.mark.skipif(sys.version_info < (3, 14), reason="zstd requires Python 3.14 or higher")
    def test_create_tar_zst(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = replace(profile_to_settings[d['profile']], archive_format='tar.zst')
        rumar = Rumar({profile: settings})
        rumar._init_for_profile(profile)
        rathers = d['rathers']
        rather = rathers[14]
        rumar._set_rath_and_friends(rather)
        actual_archive_path, actual_checksum = rumar._create(CreateReason.CREATE)
        assert actual_archive_path == rumar._archive_path
        assert actual_checksum == rather.checksum
        # print('\n##', f"archive_path: {archive_path}")
        self.compare_archive_contents([actual_archive_path], [rather], settings)

    def test_create_for_profile__all__tar(self):
        _test_create_for_profile__all_('tar', self.compare_archive_contents)

    def test_create_for_profile__all__tar_gz(self):
        _test_create_for_profile__all_('tar.gz', self.compare_archive_contents)

    def test_create_for_profile__all__tar_bz2(self):
        _test_create_for_profile__all_('tar.bz2', self.compare_archive_contents)

    def test_create_for_profile__all__tar_xz(self):
        _test_create_for_profile__all_('tar.xz', self.compare_archive_contents)

    @pytest.mark.skipif(sys.version_info < (3, 14), reason="zstd requires Python 3.14 or higher")
    def test_create_for_profile__all__tar_zst(self):
        _test_create_for_profile__all_('tar.zst', self.compare_archive_contents)

    @staticmethod
    def compare_archive_contents(created_archives: list[Path], rathers: list[Rather], settings: Settings):
        """
        :param created_archives: must be sorted
        :param rathers: must be sorted
        """
        member = None
        contents = None
        for archive_path, rather in zip(created_archives, rathers, strict=True):
            # print(f'\n## archive_path: {archive_path}')
            with tarfile.open(archive_path, 'r') as tf:
                member = tf.next()
                contents = tf.extractfile(member).read()
            assert member.name == rather.name
            assert member.mtime == rather._mtime
            assert member.size == rather._size
            assert contents == rather._content_as_fileobj().read()


def _test_create_for_profile__all_(archive_format: str, compare_archive_contents: Callable[[list[Path], list[Rather], Settings], None], settings_overrides: dict = None):
    settings_overrides = settings_overrides or {}
    # use per-function environment set-up (tmp, rumardb)
    d = _set_up_rumar()  # must be called after set_up_rumar() fixture is called
    profile = d['profile']
    profile_to_settings = d['profile_to_settings']
    settings = profile_to_settings[profile]
    settings = replace(settings, db_path=None, archive_format=archive_format, password=password, **settings_overrides)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    rumar = Rumar({profile: settings})
    created_archives = sorted(rumar.create_for_profile(profile))
    rathers: list[Rather] = sorted(d['rathers'])
    expected = [rather.compose_archive_path(rumar, settings) for rather in rathers]
    assert created_archives == expected
    # format-specific function i.e., different for tar and zipx
    compare_archive_contents(created_archives, rathers, settings)


class TestCreateZipx:

    def test_create_zipx(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings, archive_format='zipx', password=password, zip_compression_method=ZIP_ZSTANDARD, compression_level=0)
        rumar = Rumar({profile: settings})  # new Rumar, with local settings
        rumar._init_for_profile(profile)
        rathers = d['rathers']
        rather = rathers[14]
        rumar._set_rath_and_friends(rather)
        actual_archive_path, actual_checksum = rumar._create(CreateReason.CREATE)
        assert actual_archive_path == rumar._archive_path
        assert actual_checksum == rather.checksum
        # print('\n##', f"archive_path: {archive_path}")
        self.compare_archive_contents([actual_archive_path], [rather], settings)

    def test_create_for_profile__all__zipx(self):
        _test_create_for_profile__all_('zipx', self.compare_archive_contents, {'zip_compression_method': ZIP_ZSTANDARD, 'compression_level': 0})

    @staticmethod
    def compare_archive_contents(created_archives: list[Path], rathers: list[Rather], settings: Settings):
        for archive_path, rather in zip(created_archives, rathers, strict=True):
            ## verify metadata (they aren't encrypted)
            zipinfo = None
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zipinfo = next(iter(zf.infolist()))
            assert zipinfo.filename == rather.name
            assert datetime(*zipinfo.date_time) == datetime.fromtimestamp(rather._mtime).replace(microsecond=0)
            assert zipinfo.file_size == rather._size
            ## unpack and verify content
            with archive_path.open('rb') as fi:
                for file_name, _size_not_available, zipped_chunks in stream_unzip(iter(lambda: fi.read(65536), b''), chunk_size=65536, password=settings.password):
                    assert file_name.decode(UTF8) == rather.name
                    assert b''.join(zipped_chunks) == rather.open('rb').read()
                    break
