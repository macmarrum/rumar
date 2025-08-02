# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
import tarfile
from dataclasses import replace
from pathlib import Path
from textwrap import dedent

import pytest

from rumar import Rumar, make_profile_to_settings_from_toml_text, Rath, iter_all_files, iter_matching_files, is_dir_matching_top_dirs, derive_relative_p, CreateReason, compute_blake2b_checksum
from utils import Rather, eq_list


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
                           included_files_as_glob=['**/*1.*'],
                           )
        rumar = d['rumar']
        R = lambda p: Rather(p, lstat_cache=rumar.lstat_cache).as_rath()
        expected = [R(f"/{profile}/AA/file11.txt"), ]
        top_rath = R(f"/{profile}")
        actual = list(iter_matching_files(top_rath, settings))
        assert eq_list(actual, expected)

    def test_create_tar(self, set_up_rumar):
        d = set_up_rumar
        profile = d['profile']
        profile_to_settings = d['profile_to_settings']
        settings = profile_to_settings[profile]
        rumar = d['rumar']
        reason = CreateReason.CREATE
        rathers = d['rathers']
        rather = rathers[14]
        relative_p = derive_relative_p(rather, settings.source_dir)
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
