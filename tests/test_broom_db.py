# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import replace
from pathlib import Path

import pytest

from rumar import Settings, Broom


class f:
    profile = 'profile'
    settings = 'settings'
    paths = 'paths'
    bdb = 'bdb'


@pytest.fixture(scope='module')
def lifecycle():
    Broom.make_table_suffix = str  # broom without _profile_name
    data = {
        f.settings: Settings(
            profile=f.profile,
            backup_base_dir='/backup/base/dir',
            source_dir='/source/dir',
            db_path=':memory:',
        ),
        f.paths: []
    }
    for fspath in (
            # week 48
            '/a/2025-12-01_00,01,01',  # 0
            '/a/2025-12-01_00,01,02',  # 1
            '/a/2025-12-01_00,01,03',  # 2
            '/a/2025-12-01_00,01,04',  # 3
            '/a/2025-12-02_00,01,01',  # 4
            '/a/2025-12-02_00,01,02',  # 5
            '/a/2025-12-02_00,01,03',  # 6
            '/a/2025-12-02_00,01,04',  # 7
            # week 49
            '/a/2025-12-08_00,01,01',  # 8
            '/a/2025-12-08_00,01,02',  # 9
            '/a/2025-12-08_00,01,03',  # 10
            '/a/2025-12-08_00,01,04',  # 11
            # week 50
            '/a/2025-12-15_00,01,01',  # 12
            '/a/2025-12-15_00,01,02',  # 13
            '/a/2025-12-15_00,01,03',  # 14
            '/a/2025-12-15_00,01,04',  # 15
            # week 51
            '/a/2025-12-22_00,01,01',  # 16
            '/a/2025-12-22_00,01,02',  # 17
            '/a/2025-12-22_00,01,03',  # 18
            '/a/2025-12-22_00,01,04',  # 19
    ):
        path = Path(fspath)
        data[f.paths].append(path)
    yield data


def _build_actual_and_expected(lifecycle, d, w, m, expected_indexes, where):
    settings = replace(
        lifecycle[f.settings],
        number_of_backups_per_day_to_keep=d,
        number_of_backups_per_week_to_keep=w,
        number_of_backups_per_month_to_keep=m,
    )
    bdb = Broom(f.profile, settings, {}, None)
    lifecycle[f.bdb] = bdb
    paths = lifecycle[f.paths]
    for path in paths:
        bdb.insert(path, bdb.derive_date(path.name))
    bdb.calc_cnt_and_update_keep_flag_for_each_period()
    expected = []
    for i in expected_indexes:
        expected.append(paths[i])
    actual = []
    for row in bdb._db.execute(f"SELECT bak_parent, bak_name FROM broom WHERE {where} ORDER BY id"):
        actual.append(Path(*row))
    print()
    for row in bdb._db.execute(f"SELECT * FROM broom ORDER BY id"):
        print(' | '.join((f"{'' if e is None else e!s:{'22' if i in (9, 10, 11) else '>3' if i == 0 else '0'}}" for i, e in enumerate(row))))
    return actual, expected


def test_marked_for_keeping__d_1(lifecycle):
    actual, expected = _build_actual_and_expected(
        lifecycle,
        d=1, w=0, m=0,
        expected_indexes=(3, 7, 11, 15, 19),
        where='d_keep = 1 AND w_keep = 0 AND m_keep = 0'
    )
    assert actual == expected


def test_marked_for_keeping__d_2(lifecycle):
    actual, expected = _build_actual_and_expected(
        lifecycle,
        d=2, w=0, m=0,
        expected_indexes=(2, 3, 6, 7, 10, 11, 14, 15, 18, 19),
        where='d_keep = 1 AND w_keep = 0 AND m_keep = 0'
    )
    assert actual == expected


def test_marked_for_keeping__w_1(lifecycle):
    actual, expected = _build_actual_and_expected(
        lifecycle,
        d=0, w=1, m=0,
        expected_indexes=(7, 11, 15, 19),
        where='d_keep = 0 AND w_keep = 1 AND m_keep = 0'
    )
    assert actual == expected


def test_marked_for_keeping__w_2(lifecycle):
    actual, expected = _build_actual_and_expected(
        lifecycle,
        d=0, w=2, m=0,
        expected_indexes=(6, 7, 10, 11, 14, 15, 18, 19),
        where='d_keep = 0 AND w_keep = 1 AND m_keep = 0'
    )
    assert actual == expected


def test_marked_for_keeping__m_1(lifecycle):
    actual, expected = _build_actual_and_expected(
        lifecycle,
        d=0, w=0, m=1,
        expected_indexes=(19,),
        where='d_keep = 0 AND w_keep = 0 AND m_keep = 1'
    )
    assert actual == expected


def test_marked_for_keeping__m_2(lifecycle):
    actual, expected = _build_actual_and_expected(
        lifecycle,
        d=0, w=0, m=2,
        expected_indexes=(18, 19),
        where='d_keep = 0 AND w_keep = 0 AND m_keep = 1'
    )
    assert actual == expected


def test_marked_for_keeping__d_1_w_1_m_1(lifecycle):
    actual, expected = _build_actual_and_expected(
        lifecycle,
        d=1, w=1, m=1,
        expected_indexes=(3, 7, 11, 15, 19),
        where='d_keep = 1 OR w_keep = 1 OR m_keep = 1'
    )
    assert actual == expected


def test_marked_for_keeping__d_0_w_1_m_5(lifecycle):
    actual, expected = _build_actual_and_expected(
        lifecycle,
        d=0, w=1, m=5,
        expected_indexes=(7, 11, 15, 18, 19),
        where='d_keep = 1 OR w_keep = 1 OR m_keep = 1'
    )
    assert actual == expected


def test_marked_for_keeping__d_1_w_1_m_5(lifecycle):
    actual, expected = _build_actual_and_expected(
        lifecycle,
        d=1, w=1, m=5,
        expected_indexes=(3, 7, 11, 15, 19),
        where='d_keep = 1 OR w_keep = 1 OR m_keep = 1'
    )
    assert actual == expected


def test_marked_for_keeping__d_1_w_2_m_5(lifecycle):
    actual, expected = _build_actual_and_expected(
        lifecycle,
        d=1, w=2, m=5,
        expected_indexes=(3, 7, 10, 11, 14, 15, 18, 19),
        where='d_keep = 1 OR w_keep = 1 OR m_keep = 1'
    )
    for row in lifecycle[f.bdb].iter_marked_for_removal():
        print(' | '.join((f"{e}" for e in row)))
    assert actual == expected
