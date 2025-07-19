# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later
import re
from datetime import datetime, timedelta
from textwrap import dedent

import pytest

from rumar import Rumar, make_profile_to_settings_from_toml_text, CreateReason


@pytest.fixture(scope='class')
def set_up_rumardb():
    profile = 'x'
    toml = dedent(f"""\
    version = 2
    backup_base_dir = '/test/backup-base-dir'
    db_path = ':memory:'

    ['{profile}']
    source_dir = '/test/source-dir'
    """)
    profile_to_settings = make_profile_to_settings_from_toml_text(toml)
    rumar = Rumar(profile_to_settings)
    rumar._at_beginning(profile)
    rumardb = rumar._rdb
    db = rumardb._db
    file = None
    for row in db.execute("SELECT file FROM pragma_database_list WHERE name = 'main'"):
        file = row[0]
    assert file == ''
    first_datetime = datetime(2025, 6, 29, 0, 0, 0)
    mtimestr_size_fakeb2_gen = ((first_datetime + timedelta(seconds=i), 100 + i, f"abcdef{i:02}") for i in range(59))

    def make_rumardb_record(_reason, relative_p: str):
        reason = {'C': CreateReason.CREATE, 'U': CreateReason.UPDATE, 'D': CreateReason.DELETE, 'I': CreateReason.INIT}[_reason]
        archive_dir = rumar.compose_archive_container_dir(relative_p=relative_p)
        mtimestr_size_fakeb2 = next(mtimestr_size_fakeb2_gen)
        archive_path = rumar.compose_archive_path(archive_dir, *mtimestr_size_fakeb2)
        return [reason, relative_p, archive_path, mtimestr_size_fakeb2[-1]]

    rumardb_records = [
        make_rumardb_record('I', '1.txt'),
        make_rumardb_record('C', '2.txt'),
        make_rumardb_record('C', '3.txt'),
        make_rumardb_record('D', '1.txt'),
        make_rumardb_record('C', '4.txt'),
    ]
    rumardb_records[4][-1] = None  # no fakeb2 for 4.txt
    for record in rumardb_records:
        rumardb.save(*record)

    d = dict(
        rumar=rumar,
        rumardb=rumardb,
        rumardb_records=rumardb_records
    )
    yield d


class TestRumarDB:

    def test_save_done_in_set_up(self, set_up_rumardb):
        d = set_up_rumardb
        rumar = d['rumar']
        rumardb = d['rumardb']
        records = d['rumardb_records']
        db = rumardb._db
        run_date_iso = datetime.today().strftime('%Y-%m-%d')
        bak_dir = rumar.s.backup_base_dir_for_profile.as_posix()
        for i, actual in enumerate(db.execute('SELECT * FROM v_backup')):
            # run_date_is, profile, reason, bak_dir, src_path, bak_name, _b2_10 = actual
            reason, relative_p, archive_path, fake2b = records[i]
            _reason = reason.name[0]
            expected = (run_date_iso, rumar.s.profile, _reason, bak_dir, relative_p, archive_path.name, fake2b)
            assert actual == expected

    def test_get_blake2b_checksum(self, set_up_rumardb):
        d = set_up_rumardb
        rumardb = d['rumardb']
        records = d['rumardb_records']
        for record in records:
            _, _, archive_path, fakeb2 = record
            assert fakeb2 == rumardb.get_blake2b_checksum(archive_path)

    def test_set_blake2b_checksum_when_not_yet_in_backup(self, set_up_rumardb):
        d = set_up_rumardb
        rumardb = d['rumardb']
        records = d['rumardb_records']
        input_value = 'a4'
        for record in records:
            _, _, archive_path, fakeb2 = record
            if fakeb2 is None:
                rumardb.set_blake2b_checksum(archive_path, input_value)
                assert rumardb.get_blake2b_checksum(archive_path) == input_value

    def test_set_blake2b_checksum_when_already_in_backup(self, set_up_rumardb):
        d = set_up_rumardb
        rumardb = d['rumardb']
        records = d['rumardb_records']
        input_value = 'a4'
        rx_already_in_backup = re.compile(r'.+ already in backup with a different blake2b_checksum: .+')
        for record in records:
            _, _, archive_path, fakeb2 = record
            if fakeb2 is not None:
                with pytest.raises(ValueError, match=rx_already_in_backup):
                    rumardb.set_blake2b_checksum(archive_path, input_value)
