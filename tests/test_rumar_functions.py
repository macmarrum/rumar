from dataclasses import asdict
from pathlib import PureWindowsPath, PurePosixPath, Path
from textwrap import dedent

import pytest

from rumar import find_matching_full_glob_path, Settings, RX_ARCHIVE_NAME, find_on_disk_last_file_in_directory, absolutopathlify
from utils import make_absolute_path


@pytest.fixture(scope='module')
def settings():
    yield Settings(source_dir='/source/dir', backup_base_dir='/backup/dir', profile='_')


def test_make_absolute__posix_should_expand():
    expected = PurePosixPath('/source/dir/e/f/*.txt')
    actual = make_absolute_path(PurePosixPath('/source/dir'), 'e/f/*.txt')
    assert actual == expected


def test_make_absolute__posix_starstar_should_expand():
    expected = PurePosixPath('/source/dir/**/*.txt')
    actual = make_absolute_path(PurePosixPath('/source/dir'), '**/*.txt')
    assert actual == expected


def test_make_absolute__posix_questionmark_should_expand():
    expected = PurePosixPath('/source/dir/?/*.txt')
    actual = make_absolute_path(PurePosixPath('/source/dir'), '?/*.txt')
    assert actual == expected


def test_make_absolute__posix_seq_should_expand():
    expected = PurePosixPath('/source/dir/[a-zA-Z_]/*.txt')
    actual = make_absolute_path(PurePosixPath('/source/dir'), '[a-zA-Z_]/*.txt')
    assert actual == expected


def test_make_absolute__posix_should_keep():
    expected = PurePosixPath('/other/dir/e/f/*.txt')
    actual = make_absolute_path(PurePosixPath('/source/dir'), '/other/dir/e/f/*.txt')
    assert actual == expected


def test_make_absolute__nt_backslash_pattern_should_expand():
    expected = PureWindowsPath(r'c:\source\dir\e\f\*.txt')
    actual = make_absolute_path(PureWindowsPath(r'c:\source\dir'), r'e\f\*.txt')
    assert actual == expected


def test_make_absolute__nt_slash_pattern_should_expand():
    expected = PureWindowsPath(r'c:\source\dir\e\f\*.txt')
    actual = make_absolute_path(PureWindowsPath(r'c:\source\dir'), 'e/f/*.txt')
    assert actual == expected


def test_make_absolute__nt_dot_slash_pattern_should_expand():
    expected = PureWindowsPath(r'c:\source\dir\e\f\*.txt')
    actual = make_absolute_path(PureWindowsPath(r'c:\source\dir'), './e/f/*.txt')
    assert actual == expected


def test_find_matching_full_glob_path__posix_absolute_exact_should_match(settings):
    included_files = ['/source/dir/a/b/c.txt']
    d = asdict(settings) | dict(included_files=included_files)
    settings = Settings(**d)
    file_path = PurePosixPath('/source/dir/a/b/c.txt')
    assert find_matching_full_glob_path(file_path, absolutopathlify(settings.included_files, settings.source_dir))


def test_find_matching_full_glob_path__posix_relative_exact_should_match(settings):
    included_files = ['a/b/c.txt']
    d = asdict(settings) | dict(included_files=included_files)
    settings = Settings(**d)
    file_path = PurePosixPath('/source/dir/a/b/c.txt')
    assert find_matching_full_glob_path(file_path, absolutopathlify(settings.included_files, settings.source_dir))


def test_find_matching_full_glob_path__posix_absolute_starstar_should_match(settings):
    included_files = ['/source/dir/**/c.txt']
    d = asdict(settings) | dict(included_files=included_files)
    settings = Settings(**d)
    file_path = PurePosixPath('/source/dir/a/b/c.txt')
    assert find_matching_full_glob_path(file_path, absolutopathlify(settings.included_files, settings.source_dir))


def test_find_matching_full_glob_path__posix_relative_starstar_should_match(settings):
    included_files = ['a/**/c.txt']
    d = asdict(settings) | dict(included_files=included_files)
    settings = Settings(**d)
    file_path = PurePosixPath('/source/dir/a/b/c.txt')
    assert find_matching_full_glob_path(file_path, absolutopathlify(settings.included_files, settings.source_dir))


def test_find_on_disk_last_file_in_directory__without_nonzero_check():
    directory = Path('/base')
    files = [ln for ln in dedent('''\
        2024-08-03_07,23,10.700584+02,00~622.tar.gz
        2024-11-18_22,55,23.718723+01,00~633.tar.gz
        2025-09-09_07,34,20.318301+02,00~761~comment.tar.gz
        ''').splitlines() if ln and not ln.startswith('#')]
    expected = directory / files[-1]
    actual = find_on_disk_last_file_in_directory(directory, files, RX_ARCHIVE_NAME, nonzero=False)
    assert actual == expected, f"Expected {expected}, but got {actual}"
