# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
import tarfile
from dataclasses import replace
from pathlib import Path
from textwrap import dedent

import pytest

from rumar import Rumar, make_profile_to_settings_from_toml_text, Rath, iter_all_files, iter_matching_files, derive_relative_psx, CreateReason, can_exclude_dir, can_include_dir, can_exclude_file, can_include_file
from utils import Rather, eq_list


def _can_match_dir(path, s, relative_psx):
    if can_exclude_dir(path, s, relative_psx):
        return False
    return can_include_dir(path, s, relative_psx)


def _can_match_file(path, s, relative_psx):
    if can_exclude_file(path, s, relative_psx):
        return False
    return can_include_file(path, s, relative_psx)


@pytest.fixture(scope='class')
def set_up_rumar():
    BASE = Path('/tmp/rumar')
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
    rumardb = rumar._rdb
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
    raths = [r.as_rath() for r in rathers]
    d = dict(
        profile=profile,
        profile_to_settings=profile_to_settings,
        rumar=rumar,
        rathers=rathers,
        raths=raths,
    )
    yield d
    rumar.lstat_cache.clear()
    rumardb.close_db()
    rumardb._profile_to_id.clear()
    rumardb._run_to_id.clear()
    rumardb._src_dir_to_id.clear()
    rumardb._source_to_id.clear()
    rumardb._bak_dir_to_id.clear()
    rumardb._backup_to_checksum.clear()


class TestRumarCore:

    def test_001_fs_iter_all_files(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        rumar: Rumar = d['rumar']
        raths: list[Rath] = d['raths']
        expected = sorted(raths)
        top_dir = Rather(f"/{profile}", lstat_cache=rumar.lstat_cache)
        actual = sorted(iter_all_files(top_dir))
        assert eq_list(actual, expected)

    def test_can_match_dir__no_inc__no_exc(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        settings = replace(settings,  # NOTE: update local settings dict, not in rumar
                           included_files_as_glob=['*.csv'],
                           excluded_files_as_glob=['*1.*'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': True,
            'A': True,
            'AA': True,
            'B': True,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    def test_can_match_dir__inc_top_dir_single__no_exc(self, set_up_rumar):
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
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': True,
            'A': False,
            'AA': True,
            'B': False,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    def test_can_match_dir__no_inc__exc_top_dir_several(self, set_up_rumar):
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
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': True,
            'A': False,
            'AA': True,
            'B': False,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    def test_can_match_dir__no_inc__exc_top_dir_multi_level(self, set_up_rumar):
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
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': True,
            'A': True,
            'AA': True,
            'B': False,
            'A/A-A': False,
            'A/A-B': True,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    def test_can_match_dir__inc_top_dir_single__exc_top_dir_subdir(self, set_up_rumar):
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
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': True,
            'A': True,
            'AA': False,
            'B': False,
            'A/A-A': False,
            'A/A-B': True,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    def test_can_match_dir__no_inc__exc_top_dir_single_subdir(self, set_up_rumar):
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
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        expected = {
            '': True,
            'A': True,
            'AA': True,
            'B': True,
            'A/A-A': False,
            'A/A-B': True,
        }
        actual = {
            psx: _can_match_dir(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

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
            'file01.txt': False,
            'file02.txt': False,
            'file03.csv': True,
            'A/file04.txt': False,
            'A/file05.txt': False,
            'A/file06.csv': True,
            'B/file07.txt': False,
            'B/file08.txt': False,
            'B/file09.csv': True,
            'AA/file10.txt': True,
            'AA/file11.txt': False,
            'AA/file12.csv': True,
            'A/A-A/file13.txt': True,
            'A/A-A/file14.txt': False,
            'A/A-A/file15.csv': False,
            'A/A-B/file16.txt': True,
            'A/A-B/file17.txt': True,
            'A/A-B/file18.csv': True,
        }
        actual = {
            psx: _can_match_file(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    def test_derive_relative_p_with_leading_slash(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        top_rath = R('A')
        dir_rath = R('A/B/C/c1.txt')
        expected = '/B/C/c1.txt'
        actual = derive_relative_psx(dir_rath, top_rath, with_leading_slash=True)
        assert actual == expected

    def test_derive_relative_p_without_leading_slash(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        rumar = d['rumar']
        R = lambda p: Rather(f"{profile}/{p}", lstat_cache=rumar.lstat_cache)
        top_rath = R('A')
        dir_rath = R('A/B/C/c1.txt')
        expected = 'B/C/c1.txt'
        actual = derive_relative_psx(dir_rath, top_rath, with_leading_slash=False)
        assert actual == expected

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
            'file01.txt': True,
            'file02.txt': False,
            'file03.csv': False,
            'A/file04.txt': False,
            'A/file05.txt': False,
            'A/file06.csv': False,
            'B/file07.txt': False,
            'B/file08.txt': False,
            'B/file09.csv': False,
            'AA/file10.txt': True,
            'AA/file11.txt': True,
            'AA/file12.csv': True,
            'A/A-A/file13.txt': False,
            'A/A-A/file14.txt': False,
            'A/A-A/file15.csv': False,
            'A/A-B/file16.txt': False,
            'A/A-B/file17.txt': False,
            'A/A-B/file18.csv': False,
        }
        actual = {
            psx: _can_match_file(r := R(psx), settings, derive_relative_psx(r, r.BASE_PATH, with_leading_slash=True))
            for psx in expected.keys()
        }
        assert actual == expected

    def test_create_tar(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        rumar = d['rumar']
        reason = CreateReason.CREATE
        rathers = d['rathers']
        rather = rathers[14]
        relative_p = derive_relative_psx(rather, settings.source_dir)
        archive_dir = rumar.compose_archive_container_dir(relative_p=relative_p)
        lstat = rather.lstat()
        mtime_str = rumar.calc_mtime_str(lstat)
        size = lstat.st_size
        checksum = rather.checksum
        rumar._create_tar(reason, rather, relative_p, archive_dir, mtime_str, size, checksum)
        archive_path = rumar.compose_archive_path(archive_dir, mtime_str, size, '')
        actual_checksum = rumar.compute_checksum_of_file_in_archive(archive_path, settings.password)
        assert actual_checksum == checksum
        member = None
        with tarfile.open(archive_path, 'r') as tf:
            member = tf.next()
        assert member.name == rather.name
        assert member.mtime == lstat.st_mtime
        assert member.size == size
