from pathlib import PureWindowsPath, PurePosixPath

import pytest

from rumar import is_file_glob_match, Settings
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


def test_is_file_glob_match__posix_absolute_exact_should_match(settings):
    settings.included_files = ['/source/dir/a/b/c.txt']
    file_path = PurePosixPath('/source/dir/a/b/c.txt')
    assert is_file_glob_match(file_path, settings, '')


def test_is_file_glob_match__posix_relative_exact_should_match(settings):
    settings.included_files = ['a/b/c.txt']
    file_path = PurePosixPath('/source/dir/a/b/c.txt')
    assert is_file_glob_match(file_path, settings, '')


def test_is_file_glob_match__posix_absolute_starstar_should_match(settings):
    settings.included_files = ['/source/dir/**/c.txt']
    file_path = PurePosixPath('/source/dir/a/b/c.txt')
    assert is_file_glob_match(file_path, settings, '')


def test_is_file_glob_match__posix_relative_starstar_should_match(settings):
    settings.included_files = ['a/**/c.txt']
    file_path = PurePosixPath('/source/dir/a/b/c.txt')
    assert is_file_glob_match(file_path, settings, '')
