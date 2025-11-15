# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later
import re
import shutil
from pathlib import Path
from textwrap import dedent

import pytest

from rumar import Rumar, make_profile_to_settings_from_toml_text, CreateReason
from utils import Rather


def _set_up_rumar():
    BASE_PATH = Path('/tmp/rumar')
    Rather.BASE_PATH = BASE_PATH
    profile = 'profileA'
    toml = dedent(f"""\
    version = 2
    db_path = ':memory:'
    backup_base_dir = '{BASE_PATH}/backup'
    [{profile}]
    source_dir = '{BASE_PATH}/{profile}'
    """)
    profile_to_settings = make_profile_to_settings_from_toml_text(toml)
    # clean up any existing BASE_PATH tree
    if BASE_PATH.exists():
        shutil.rmtree(BASE_PATH)
    s = profile_to_settings[profile]
    assert s.backup_dir == BASE_PATH / 'backup' / profile
    if 'memory' not in str(s.db_path):
        s.db_path.parent.mkdir(parents=True, exist_ok=True)
    rumar = Rumar(profile_to_settings)
    rumar._init_for_profile(profile)
    assert rumar.s.backup_dir == BASE_PATH / 'backup' / profile
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
    archive_rathers: list[Rather] = []
    checksums: list[bytes] = []
    reason = CreateReason.CREATE
    Rather.BASE_PATH = None
    for rather in rathers:
        rumar._set_rath_and_friends(rather)
        archive_rather = Rather(rumar._archive_path, lstat_cache=rumar.lstat_cache, mtime=rumar._mtime, content='x' * rumar._size)
        reasons.append(reason)
        relative_ps.append(rumar._relative_psx)
        archive_rathers.append(archive_rather)
        checksums.append(rather.checksum)
        rumardb.save(reason, rumar._relative_psx, archive_rather, rather.checksum)
    Rather.BASE_PATH = BASE_PATH
    # db = rumardb._db
    # print("\n### Database Tables ###")
    # for table, dictionary in [
    #     ('profile', '_profile_to_id'),
    #     ('run', '_run_to_id'),
    #     ('source_dir', '_src_dir_to_id'),
    #     ('source', '_source_to_id'),
    #     ('backup_dir', '_bak_dir_to_id'),
    #     ('backup', '_backup_to_checksum'),
    # ]:
    #     print(f"\n{table}:")
    #     for row in db.execute(f'SELECT * FROM {table}'):
    #         print(row)
    #     print(f"\n{dictionary}:")
    #     for items in getattr(rumardb, dictionary).items():
    #         print(items)
    d = dict(
        BASE_PATH=BASE_PATH,
        profile=profile,
        profile_to_settings=profile_to_settings,
        rumar=rumar,
        rumardb=rumardb,
        rathers=rathers,
        raths=raths,
        data=dict(reasons=reasons, relative_ps=relative_ps, archive_rathers=archive_rathers, checksums=checksums),
    )
    return d


def _tear_down_rumar(d):
    rumar = d['rumar']
    rumardb = d['rumardb']
    rumar.lstat_cache.clear()
    db = rumardb._db
    for table in ['backup',
                  'backup_dir',
                  'source_lc',
                  'source',
                  'source_dir',
                  'run',
                  'profile',
                  ]:
        db.execute(f"DELETE FROM {table}")
    db.commit()
    rumardb.close_db()
    rumardb._profile_to_id.clear()
    rumardb._run_to_id.clear()
    rumardb._src_dir_to_id.clear()
    rumardb._source_to_id.clear()
    rumardb._bak_dir_to_id.clear()
    rumardb._backup_to_checksum.clear()


@pytest.fixture(scope='class')
def set_up_rumar():
    d = _set_up_rumar()
    yield d
    _tear_down_rumar(d)


class TestRumarDB:

    def test_rumardb_init(self, set_up_rumar):
        d = set_up_rumar
        rumar = d['rumar']
        data = d['data']
        db = rumar._rdb._db
        bak_dir = rumar.s.backup_dir.as_posix()
        for i, actual in enumerate(db.execute('SELECT profile, reason, bak_dir, src_path, bak_name, blake2b FROM v_backup')):
            reason: CreateReason = data['reasons'][i]
            relative_p = data['relative_ps'][i]
            archive_path: Path = data['archive_rathers'][i]
            blake2b = data['checksums'][i]  # bytes | None
            if blake2b is not None:
                blake2b = blake2b.hex()  # str
            assert actual == (rumar.s.profile, reason.name[0], bak_dir, relative_p, archive_path.name, blake2b)

    def test_get_blake2b_checksum(self, set_up_rumar):
        d = set_up_rumar
        rumardb = d['rumardb']
        data = d['data']
        archive_rathers = data['archive_rathers']
        checksums = data['checksums']
        for i in range(len(checksums)):
            assert checksums[i] == rumardb.get_blake2b_checksum(archive_rathers[i])

    def test_set_blake2b_checksum_when_not_yet_in_backup(self, set_up_rumar):
        d = set_up_rumar
        data = d['data']
        rumardb = d['rumardb']
        db = rumardb._db
        archive_path = data['archive_rathers'][0]
        relative_p = data['relative_ps'][0]
        ## verify in RumarDB the initial state of checksum is NULL
        assert (src_id := rumardb.get_src_id(relative_p)) is not None
        assert rumardb._backup_to_checksum[(rumardb.bak_dir_id, src_id, archive_path.name)] is None
        ## test methods to set and get checksum
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
        archive_path = data['archive_rathers'][1]
        rx_already_in_backup = re.compile(r'.+ already in backup with a different blake2b_checksum: .+')
        input_checksum = bytes.fromhex('b2c3d4e5')
        with pytest.raises(ValueError, match=rx_already_in_backup):
            rumardb.set_blake2b_checksum(archive_path, input_checksum)

    def test_iter_latest_archives_and_targets_no_deleted_and_no_top_archive_dir_and_no_directory(self, set_up_rumar):
        d = set_up_rumar
        rumardb = d['rumardb']
        raths = d['raths']
        data = d['data']
        archive_rathers = data['archive_rathers']
        expected = list(zip(archive_rathers, raths))
        actual = list(rumardb.iter_latest_archives_and_targets())
        assert actual == expected

    def test_iter_latest_archives_and_targets_no_deleted_and_no_top_archive_dir_and_directory(self, set_up_rumar):
        d = set_up_rumar
        rumardb = d['rumardb']
        data = d['data']
        archive_rathers = data['archive_rathers']
        directory = Path('/tmp/a-different-directory')
        targets = []
        for relative_p in data['relative_ps']:
            targets.append(directory / relative_p)
        expected = list(zip(archive_rathers, targets))
        actual = list(rumardb.iter_latest_archives_and_targets(directory=directory))
        assert actual == expected

    def test_iter_latest_archives_and_targets_no_deleted_and_top_archive_dir_and_no_directory(self, set_up_rumar):
        d = set_up_rumar
        rumar = d['rumar']
        rumardb = d['rumardb']
        raths = d['raths']
        data = d['data']
        archive_rathers = data['archive_rathers']
        top_archive_dir = Path(rumar.s.backup_dir, 'A')
        expected = [(a, t) for (a, t) in zip(archive_rathers, raths) if a.as_posix().startswith(top_archive_dir.as_posix())]
        actual = list(rumardb.iter_latest_archives_and_targets(top_archive_dir=top_archive_dir))
        assert actual == expected

    def test_iter_latest_archives_and_targets_deleted_and_no_top_archive_dir_and_no_directory(self):
        d = _set_up_rumar()
        rumar = d['rumar']
        rumardb = d['rumardb']
        rathers = d['rathers']
        data = d['data']
        archive_rathers = data['archive_rathers']
        ## mark source file #1 as deleted
        src_id = 1
        rumardb.init_run_datetime_iso_anew()
        db = rumardb._db
        db.execute('INSERT INTO source_lc (src_id, reason, run_id) VALUES (?, ?, ?)', (src_id, CreateReason.DELETE.name[0], rumardb.run_id,))
        db.commit()
        ## add another backup for file #2 (index 1)
        i = 1
        rather = rathers[i].clone()
        rather.content = rather.content + '\n' + rumardb._run_datetime_iso
        lstat = rather.lstat()
        updated_archive_path1 = rumar.compose_archive_path(archive_rathers[i].parent, rumar.calc_mtime_str(lstat), lstat.st_size)
        rumardb.save(CreateReason.UPDATE, data['relative_ps'][i], updated_archive_path1, rather.checksum)
        ## mark the updated backup as deleted, so that its previous backup is used, i.e. file #2 (index 1)
        rumardb.mark_backup_as_deleted(updated_archive_path1)
        ## verify
        expected_archive_paths = [r.as_path() for r in archive_rathers[1:]]
        expected_target_paths = [r.as_path() for r in rathers[1:]]
        expected = list(zip(expected_archive_paths, expected_target_paths))
        actual = list(rumardb.iter_latest_archives_and_targets())
        assert actual == expected
        ## clean up
        _tear_down_rumar(d)

    def test_save_unchanged(self, set_up_rumar):
        d = set_up_rumar
        data = d['data']
        rumardb = d['rumardb']
        db = rumardb._db
        ## verify in RumarDB the initial state of unchanged rows in 0
        actual_unchanged_rows_count = db.execute('SELECT count(*) FROM unchanged').fetchone()[0]
        assert actual_unchanged_rows_count == 0
        ## call save_unchanged and verify it's been persisted in the DB
        expected_unchanged = []
        relative_ps = data['relative_ps']
        for i, relative_p in enumerate(relative_ps):
            if i % 3 == 0:
                src_id = rumardb.get_src_id(relative_p)
                rumardb.save_unchanged(src_id)
                expected_unchanged.append(src_id)
        actual_unchanged = [row[0] for row in db.execute('SELECT src_id FROM unchanged')]
        assert actual_unchanged == expected_unchanged
        ## clean up for next tests
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
        d = set_up_rumar
        raths = d['raths']
        rathers = d['rathers']
        data = d['data']
        relative_ps = data['relative_ps']
        archive_rathers = data['archive_rathers']
        rumardb = d['rumardb']
        rumar = d['rumar']
        db = rumardb._db
        ## generate a new run
        rumardb.init_run_datetime_iso_anew()
        ## update rather
        rather = rathers[1].clone()
        rather.content = rather.content + '\n' + rumardb._run_datetime_iso
        archive_dir = archive_rathers[1].parent
        archive_path = rumar.compose_archive_path(archive_dir, rumar.calc_mtime_str(rather.lstat()), rather.lstat().st_size)
        rumardb.save(CreateReason.UPDATE, relative_ps[1], archive_path, rather.checksum)
        ## update d for next tests
        rathers.append(rather)
        raths.append(rather.as_rath())
        Rather.BASE_PATH = None
        archive_rather = Rather(archive_path, lstat_cache=rumar.lstat_cache, mtime=rather.lstat().st_mtime, content=rather.content)
        data['archive_rathers'].append(archive_rather)
        Rather.BASE_PATH = d['BASE_PATH']
        ## mark unchanged files
        input_not_unchanged = []
        expected_unchanged = []
        for i, relative_p in enumerate(relative_ps):
            src_id = rumardb.get_src_id(relative_p)
            if i % 3 == 0 and i != 0:  # file idx0 was already deleted in test_iter_latest_archives_and_targets_deleted_and_no_top_archive_dir_and_no_directory
                rumardb.save_unchanged(src_id)
                expected_unchanged.append(src_id)
            else:
                input_not_unchanged.append(src_id)
        actual_unchanged = [row[0] for row in db.execute('SELECT src_id FROM unchanged')]
        assert actual_unchanged == expected_unchanged
        ## call the method under test
        rumardb.identify_and_save_deleted()
        # print data for manual debugging
        # print()
        # for table in ['unchanged', 'source_lc']:
        #     print(table)
        #     for row in db.execute('SELECT * FROM ' + table):
        #         print(row)
        ## verify
        expected_deleted = input_not_unchanged
        expected_deleted.remove(rumardb.get_src_id(relative_ps[1]))
        actual_deleted = []
        for row in db.execute('SELECT src_id FROM source_lc WHERE reason = ?', (CreateReason.DELETE.name[0],)):
            actual_deleted.append(row[0])
        ## clean up for next tests
        db.execute('DELETE FROM unchanged')
        assert actual_deleted == expected_deleted

    def test_iter_non_deleted_archive_paths(self, set_up_rumar):
        d = set_up_rumar
        data = d['data']
        rumardb = d['rumardb']
        db = rumardb._db
        archive_rathers = data['archive_rathers']
        expected = []
        for i, archive_rather in enumerate(archive_rathers):
            if i % 3 == 0:
                rumardb.mark_backup_as_deleted(archive_rather)
            else:
                expected.append(archive_rather.as_posix())
        actual = [path.as_posix() for path in rumardb.iter_non_deleted_archive_paths()]
        assert actual == expected
        ## clean up
        db.execute('UPDATE backup SET del_run_id = NULL')
        db.commit()

    def test_reconcile_backup_files_with_disk(self, set_up_rumar):
        d = set_up_rumar
        data = d['data']
        rumar = d['rumar']
        rumardb = d['rumardb']
        db = rumardb._db
        ## make only every 3rd archive_rather
        expected_deleted = []
        expected_intact = []
        for i, archive_rather in enumerate(data['archive_rathers']):
            if i % 3 == 0:
                print('++', archive_rather.make())
                expected_intact.append(archive_rather.as_path())
            else:
                expected_deleted.append(archive_rather.as_path())
        ## run the method under test
        rumar.reconcile_backup_files_with_disk()
        ## get the data for validation
        actual_deleted = []
        actual_intact = []
        query = dedent('''\
        SELECT bak_dir, src_path, bak_name, del_run_id
        FROM backup b
        JOIN backup_dir p ON b.bak_dir_id = p.id
        JOIN source s ON b.src_id = s.id
        JOIN run r ON b.run_id = r.id AND r.profile_id = ?
        ''')
        run_id = rumardb.run_id
        for i, row in enumerate(db.execute(query, (rumardb.profile_id,))):
            # print('a>', row)
            bak_dir, src_path, bak_name, del_run_id = row
            archive_path = Path(bak_dir, src_path, bak_name)
            if del_run_id:
                assert del_run_id == run_id
                actual_deleted.append(archive_path)
            else:
                actual_intact.append(archive_path)
        assert actual_intact == expected_intact
        assert actual_deleted == expected_deleted
        ## clean up
        db.execute('UPDATE backup SET del_run_id = NULL')
        db.commit()
