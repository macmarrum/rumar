# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later
import re
import shutil
from datetime import timedelta, datetime
from pathlib import Path
from textwrap import dedent

import pytest

from rumar import Rumar, make_profile_to_settings_from_toml_text, CreateReason, derive_relative_p
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
    assert s.backup_base_dir_for_profile == BASE / 'backup' / profile
    if s.db_path != ':memory:':
        s.db_path.parent.mkdir(parents=True, exist_ok=True)
    rumar = Rumar(profile_to_settings)
    rumar._at_beginning(profile)
    assert rumar.s.backup_base_dir_for_profile == BASE / 'backup' / profile
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
        archive_path = rumar.compose_archive_path(archive_dir, rumar.calc_mtime_str(rather.lstat()), rather.lstat().st_size)
        reasons.append(reason)
        relative_ps.append(relative_p)
        archive_paths.append(archive_path)
        checksums.append(rather.checksum)
        rumardb.save(reason, relative_p, archive_path, rather.checksum)
    d = dict(
        profile=profile,
        profile_to_settings=profile_to_settings,
        rumar=rumar,
        rumardb=rumardb,
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
        for i, actual in enumerate(db.execute('SELECT profile, reason, bak_dir, src_path, bak_name, blake2b FROM v_backup')):
            reason: CreateReason = data['reason'][i]
            relative_p = data['relative_p'][i]
            archive_path: Path = data['archive_path'][i]
            blake2b = data['checksum'][i]
            assert actual == (rumar.s.profile, reason.name[0], bak_dir, relative_p, archive_path.name, blake2b)

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

    def test_iter_latest_archives_and_targets_no_deleted_and_no_top_archive_dir_and_no_directory(self, set_up_rumar):
        d = set_up_rumar
        rumardb = d['rumardb']
        raths = d['raths']
        data = d['data']
        archive_paths = data['archive_path']
        expected = list(zip(archive_paths, raths))
        actual = list(rumardb.iter_latest_archives_and_targets())
        assert actual == expected

    def test_iter_latest_archives_and_targets_no_deleted_and_no_top_archive_dir_and_directory(self, set_up_rumar):
        d = set_up_rumar
        rumardb = d['rumardb']
        raths = d['raths']
        data = d['data']
        archive_paths = data['archive_path']
        directory = Path('/tmp/a-different-directory')
        targets = []
        for relative_p in data['relative_p']:
            targets.append(directory / relative_p)
        expected = list(zip(archive_paths, targets))
        actual = list(rumardb.iter_latest_archives_and_targets(directory=directory))
        assert actual == expected

    def test_iter_latest_archives_and_targets_no_deleted_and_top_archive_dir_and_no_directory(self, set_up_rumar):
        d = set_up_rumar
        rumar = d['rumar']
        rumardb = d['rumardb']
        raths = d['raths']
        data = d['data']
        archive_paths = data['archive_path']
        top_archive_dir = Path(rumar.s.backup_base_dir_for_profile, 'A')
        expected = [(a, t) for (a, t) in zip(archive_paths, raths) if a.as_posix().startswith(top_archive_dir.as_posix())]
        actual = list(rumardb.iter_latest_archives_and_targets(top_archive_dir=top_archive_dir))
        assert actual == expected

    def test_iter_latest_archives_and_targets_deleted_and_no_top_archive_dir_and_no_directory(self, set_up_rumar):
        d = set_up_rumar
        rumar = d['rumar']
        rumardb = d['rumardb']
        rathers = d['rathers']
        data = d['data']
        archive_paths = data['archive_path']
        # mark source file #1 as deleted
        src_id = 1
        db = rumardb._db
        run_datetime_iso = (datetime.now().astimezone() + timedelta(seconds=10)).isoformat(sep=' ', timespec='seconds')
        db.execute('INSERT INTO run (run_datetime_iso, profile_id) VALUES (?, ?)', (run_datetime_iso, rumardb.profile_id,))
        run_id = db.execute('SELECT max(id) FROM run').fetchone()[0]
        db.execute('INSERT INTO source_lc (src_id, reason, run_id) VALUES (?, ?, ?)', (src_id, CreateReason.DELETE.name[0], run_id,))
        db.commit()
        # add another backup for file #2 (index 1)
        i = 1
        rather = rathers[i]
        rather.content = rather.content + '\n' + run_datetime_iso
        updated_archive_path1 = rumar.compose_archive_path(archive_paths[i].parent, rumar.calc_mtime_str(rather.lstat()), rather.lstat().st_size)
        rumardb.save(CreateReason.UPDATE, data['relative_p'][i], updated_archive_path1, rather.checksum)
        # mark backup file #2 (index 1) as deleted, so that a previous backup is used
        rumardb.save(CreateReason.DELETE, data['relative_p'][i], None, None)
        # verify
        updated_archive_paths = [updated_archive_path1, *archive_paths[2:]]
        expected = list(zip(updated_archive_paths, rathers[1:]))
        actual = list(rumardb.iter_latest_archives_and_targets())
        assert actual == expected
