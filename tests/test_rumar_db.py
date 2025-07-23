# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later
import re
import shutil
from pathlib import Path
from textwrap import dedent

import pytest

from rumar import Rumar, make_profile_to_settings_from_toml_text, CreateReason, derive_relative_p, compose_archive_path, RumarFormat
from utils import Rather, _path_to_lstat_


@pytest.fixture(scope='class')
def set_up_rumar():
    BASE = Path('/tmp/rumar')
    Rather.BASE_PATH = BASE
    profile = 'profileA'
    toml = dedent(f"""\
    version = 2
    #db_path = ':memory:'
    backup_base_dir = '{BASE}/backup'
    [{profile}]
    source_dir = '{BASE}/{profile}'
    """)
    profile_to_settings = make_profile_to_settings_from_toml_text(toml)
    if BASE.exists():
        shutil.rmtree(BASE)
    s = profile_to_settings[profile]
    if s.db_path != ':memory:':
        s.db_path.parent.mkdir(parents=True, exist_ok=True)
    rumar = Rumar(profile_to_settings)
    rumar._at_beginning(profile)
    rumar_db = rumar._rdb
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
    rathers = [Rather(fs_path, lstat_cache=rumar.lstat_cache, mtime=i * 60) for i, fs_path in enumerate(fs_paths, start=1)]
    raths = [r.as_rath() for r in rathers]
    reasons: list[CreateReason] = []
    relative_ps: list[str] = []
    archive_paths: list[Path] = []
    checksums: list[str] = []
    reason = CreateReason.CREATE
    for rather in rathers:
        relative_p = derive_relative_p(rather, rumar.s.source_dir)
        archive_dir = rumar.compose_archive_container_dir(relative_p=relative_p)
        archive_path = compose_archive_path(archive_dir, RumarFormat.TGZ, rumar.calc_mtime_str(rather.lstat()), rather.lstat().st_size, '')
        reasons.append(reason)
        relative_ps.append(relative_p)
        archive_paths.append(archive_path)
        checksums.append(rather.checksum)
        rumar_db.save(reason, relative_p, archive_path, rather.checksum)
    d = dict(
        profile=profile,
        profile_to_settings=profile_to_settings,
        rumar=rumar,
        rumardb=rumar._rdb,
        rathers=rathers,
        raths=raths,
        data=dict(reason=reasons, relative_p=relative_ps, archive_path=archive_paths, checksum=checksums),
    )
    yield d
    # if BASE.exists():
    #     shutil.rmtree(BASE)
    Rather.BASE_PATH = None
    _path_to_lstat_.clear()


class TestRumarDB:

    def test_rumardb_init(self, set_up_rumar):
        d = set_up_rumar
        rumar = d['rumar']
        data = d['data']
        db = rumar._rdb._db
        bak_dir = rumar.s.backup_base_dir_for_profile.as_posix()
        for i, actual in enumerate(db.execute('SELECT profile, reason, bak_dir, src_path, bak_name, _blake2b FROM v_backup')):
            reason: CreateReason = data['reason'][i]
            relative_p = data['relative_p'][i]
            archive_path: Path = data['archive_path'][i]
            _blake2b = data['checksum'][i][:10]
            assert actual == (rumar.s.profile, reason.name[0], bak_dir, relative_p, archive_path.name, _blake2b)

    def test_get_blake2b_checksum(self, set_up_rumar):
        d = set_up_rumar
        rumardb = d['rumardb']
        data = d['data']
        archive_paths = data['archive_path']
        checksums = data['checksum']
        for i in range(len(checksums)):
            assert checksums[i] == rumardb.get_blake2b_checksum(archive_paths[i])

    def test_set_blake2b_checksum_when_not_yet_in_backup(self, set_up_rumar):
        d = set_up_rumar
        data = d['data']
        rumardb = d['rumardb']
        db = rumardb._db
        archive_path = data['archive_path'][0]
        relative_p = data['relative_p'][0]
        # set checksum to NULL in RumarDB
        src_id = None
        for row in db.execute('SELECT id FROM source s WHERE src_dir_id = ? AND src_path = ?', (rumardb.src_dir_id, relative_p,)):
            src_id = row[0]
        key = (rumardb.bak_dir_id, src_id, archive_path.name)
        rumardb._backup_to_checksum[key] = None
        db.execute('UPDATE backup SET blake2b = NULL WHERE id = (SELECT max(id) FROM backup WHERE src_id = ?)', (src_id,))
        db.commit()
        # test methods to set and get checksum
        input_value = '_test_checksum_value_1_'
        rumardb.set_blake2b_checksum(archive_path, input_value)
        checksum = None
        for row in db.execute('SELECT blake2b FROM backup WHERE id = (SELECT max(id) FROM backup WHERE src_id = ?)', (src_id,)):
            checksum = row[0]
        assert checksum == input_value  # set_blake2b_checksum()
        assert rumardb.get_blake2b_checksum(archive_path) == input_value

    def test_set_blake2b_checksum_when_already_in_backup(self, set_up_rumar):
        d = set_up_rumar
        data = d['data']
        rumardb = d['rumardb']
        archive_path = data['archive_path'][1]
        rx_already_in_backup = re.compile(r'.+ already in backup with a different blake2b_checksum: .+')
        input_value = '_test_checksum_value_1_'
        with pytest.raises(ValueError, match=rx_already_in_backup):
            rumardb.set_blake2b_checksum(archive_path, input_value)
