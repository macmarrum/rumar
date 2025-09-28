from pathlib import Path

from rumar import replace_dot_sep


def test_replace_dot_sep__dot_sep():
    expected = '/source/dir/a/b/*.txt'
    actual = replace_dot_sep('./a/b/*.txt', str(Path('/source/dir')))
    assert actual == expected

def test_replace_dot_sep__nothing_to_replace():
    expected = 'a/b/*.txt'
    actual = replace_dot_sep('a/b/*.txt', str(Path('/source/dir')))
    assert actual == expected

def test_replace_dot_sep__dot_dot_sep():
    expected = '../a/b/*.txt'
    actual = replace_dot_sep('../a/b/*.txt', str(Path('/source/dir')))
    assert actual == expected

def test_replace_dot_sep__dot_altsep():
    expected = r'c:\source\dir\a\b\*.txt'
    actual = replace_dot_sep(r'.\a\b\*.txt', str(Path(r'c:\source\dir')))
    assert actual == expected
