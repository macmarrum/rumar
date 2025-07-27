# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later
import re
import shutil
from pathlib import Path
from textwrap import dedent

import pytest

from rumar import Rumar, make_profile_to_settings_from_toml_text, CreateReason, derive_relative_p
from utils import Rather


@pytest.fixture(scope='class')
def set_up_rumar():
    BASE = Path('/tmp/rumar')
    Rather.BASE_PATH = BASE
    profile = 'profileA'
    toml = dedent(f"""\
    version = 2
    db_path = ':memory:'
    # db_path = 'file:mem{id(BASE)}?mode=memory&cache=shared'
    backup_base_dir = '{BASE}/backup'
    [{profile}]
    source_dir = '{BASE}/{profile}'
    """)
    profile_to_settings = make_profile_to_settings_from_toml_text(toml)
    # clean up any existing BASE tree
    if BASE.exists():
        shutil.rmtree(BASE)
    s = profile_to_settings[profile]
    assert s.backup_base_dir_for_profile == BASE / 'backup' / profile
    if 'memory' not in s.db_path:
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
    rathers[0].checksum = Rather.NONE  # set checksum to None while keeping content intact
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
    # db = rumardb._db
    # print("\n### Database Tables ###")
    # for table, dictionary in [
    #     ('profile', '_profile_to_id'),
    #     ('run', '_run_to_id'),
    #     ('source_dir', '_src_dir_to_id'),
    #     ('source', '_source_to_id'),
    #     ('backup_base_dir_for_profile', '_bak_dir_to_id'),
    #     ('backup', '_backup_to_checksum'),
    # ]:
    #     print(f"\n{table}:")
    #     for row in db.execute(f'SELECT * FROM {table}'):
    #         print(row)
    #     print(f"\n{dictionary}:")
    #     for items in getattr(rumardb, dictionary).items():
    #         print(items)
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
    rumar.lstat_cache.clear()
    rumardb.close_db()
    rumardb._profile_to_id.clear()
    rumardb._run_to_id.clear()
    rumardb._src_dir_to_id.clear()
    rumardb._source_to_id.clear()
    rumardb._bak_dir_to_id.clear()
    rumardb._backup_to_checksum.clear()


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
            blake2b = data['checksum'][i]  # bytes | None
            if blake2b is not None:
                blake2b = blake2b.hex()  # str
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
        # verify in RumarDB the initial state of checksum is NULL
        assert (src_id := rumardb.get_src_id(relative_p)) is not None
        assert rumardb._backup_to_checksum[(rumardb.bak_dir_id, src_id, archive_path.name)] is None
        # test methods to set and get checksum
        input_checksum = bytes.fromhex('a1b2c3d4')
        rumardb.set_blake2b_checksum(archive_path, input_checksum)
        actual_checksum = None
        for row in db.execute('SELECT blake2b FROM backup WHERE id = (SELECT max(id) FROM backup WHERE src_id = ?)', (src_id,)):
            actual_checksum = row[0]
        assert actual_checksum == input_checksum, 'set_blake2b_checksum() failed to do its job'
        assert rumardb.get_blake2b_checksum(archive_path) == input_checksum

    def test_set_blake2b_checksum_when_already_in_backup(self, set_up_rumar):
        d = set_up_rumar
        data = d['data']
        rumardb = d['rumardb']
        archive_path = data['archive_path'][1]
        rx_already_in_backup = re.compile(r'.+ already in backup with a different blake2b_checksum: .+')
        input_checksum = bytes.fromhex('b2c3d4e5')
        with pytest.raises(ValueError, match=rx_already_in_backup):
            rumardb.set_blake2b_checksum(archive_path, input_checksum)

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
        rumardb.init_run_datetime_iso_anew()
        db = rumardb._db
        db.execute('INSERT INTO source_lc (src_id, reason, run_id) VALUES (?, ?, ?)', (src_id, CreateReason.DELETE.name[0], rumardb.run_id,))
        db.commit()
        # add another backup for file #2 (index 1)
        i = 1
        rather = rathers[i]
        rather.content = rather.content + '\n' + rumardb._run_datetime_iso
        updated_archive_path1 = rumar.compose_archive_path(archive_paths[i].parent, rumar.calc_mtime_str(rather.lstat()), rather.lstat().st_size)
        rumardb.save(CreateReason.UPDATE, data['relative_p'][i], updated_archive_path1, rather.checksum)
        # mark backup file #2 (index 1) as deleted, so that a previous backup is used
        rumardb.save(CreateReason.DELETE, data['relative_p'][i], None, None)
        # verify
        updated_archive_paths = [updated_archive_path1, *archive_paths[2:]]
        expected = list(zip(updated_archive_paths, rathers[1:]))
        actual = list(rumardb.iter_latest_archives_and_targets())
        assert actual == expected

    def test_save_unchanged(self, set_up_rumar):
        d = set_up_rumar
        data = d['data']
        rumardb = d['rumardb']
        db = rumardb._db
        # verify in RumarDB the initial state of unchanged rows in 0
        actual_unchanged_rows_count = db.execute('SELECT count(*) FROM unchanged').fetchone()[0]
        assert actual_unchanged_rows_count == 0
        # call save_unchanged and verify it's been persisted in the DB
        expected_unchanged = []
        relative_ps = data['relative_p']
        for i, relative_p in enumerate(relative_ps):
            if i % 3 == 0:
                rumardb.save_unchanged(relative_p)
                src_id = rumardb.get_src_id(relative_p)
                expected_unchanged.append(src_id)
        actual_unchanged = [row[0] for row in db.execute('SELECT src_id FROM unchanged')]
        assert actual_unchanged == expected_unchanged
        # clean up for next tests
        db.execute('DELETE FROM unchanged')

    def test_init_run_datetime_iso_anew(self, set_up_rumar):
        d = set_up_rumar
        rumardb = d['rumardb']
        run_datetime_iso = rumardb._run_datetime_iso
        assert run_datetime_iso is not None
        run_id = rumardb.run_id
        assert run_id is not None
        rumardb.init_run_datetime_iso_anew()
        new_run_datetime_iso = rumardb._run_datetime_iso
        assert new_run_datetime_iso is not None
        assert new_run_datetime_iso != run_datetime_iso

    def test_identify_and_save_deleted(self, set_up_rumar):
        # d = next(_set_up_rumar())  # set it up afresh
        d = set_up_rumar
        rathers = d['rathers']
        data = d['data']
        relative_ps = data['relative_p']
        archive_paths = data['archive_path']
        rumardb = d['rumardb']
        rumar = d['rumar']
        db = rumardb._db
        # generate a new run
        rumardb.init_run_datetime_iso_anew()
        # update rather
        rather = rathers[1]
        rather.content = rather.content + '\n' + rumardb._run_datetime_iso
        archive_dir = archive_paths[1].parent
        archive_path = rumar.compose_archive_path(archive_dir, rumar.calc_mtime_str(rather.lstat()), rather.lstat().st_size)
        rumardb.save(CreateReason.UPDATE, relative_ps[1], archive_path, rather.checksum)
        # mark unchanged files
        input_not_unchanged = []
        expected_unchanged = []
        for i, relative_p in enumerate(relative_ps):
            src_id = rumardb.get_src_id(relative_p)
            if i % 3 == 0 and i != 0:  # file idx0 was already deleted in test_iter_latest_archives_and_targets_deleted_and_no_top_archive_dir_and_no_directory
                rumardb.save_unchanged(relative_p)
                expected_unchanged.append(src_id)
            else:
                input_not_unchanged.append(src_id)
        actual_unchanged = [row[0] for row in db.execute('SELECT src_id FROM unchanged')]
        assert actual_unchanged == expected_unchanged
        # call the method under test
        rumardb.identify_and_save_deleted()
        # print data for manual debugging
        # print()
        # for table in ['unchanged', 'source_lc']:
        #     print(table)
        #     for row in db.execute('SELECT * FROM ' + table):
        #         print(row)
        # verify
        expected_deleted = input_not_unchanged
        expected_deleted.remove(rumardb.get_src_id(relative_ps[1]))
        actual_deleted = []
        for row in db.execute('SELECT src_id FROM source_lc WHERE reason = ?', (CreateReason.DELETE.name[0],)):
            actual_deleted.append(row[0])
        # clean up for next tests
        db.execute('DELETE FROM unchanged')
        assert actual_deleted == expected_deleted
