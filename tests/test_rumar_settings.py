from pathlib import Path
from textwrap import dedent

import pytest

from rumar import make_profile_to_settings_from_toml_text, Settings


@pytest.fixture(scope='function')
def set_up_data():
    BASE = Path('/tmp/rumar')
    profile = 'profileA'
    toml = dedent(f"""\
    version = 2
    db_path = ':memory:'
    backup_base_dir = '{BASE}/backup-base-dir'
    [{profile}]
    source_dir = '{BASE}/{profile}'
    """)
    profile_to_settings = make_profile_to_settings_from_toml_text(toml)
    settings = profile_to_settings[profile]
    assert settings.profile == profile
    assert settings.db_path == ':memory:'
    assert settings.backup_base_dir == BASE / 'backup-base-dir'
    assert settings.source_dir == BASE / profile
    return dict(
        base=BASE,
        profile=profile,
        settings=settings,
    )


class TestSettings:

    def test_update(self, set_up_data):
        d = set_up_data
        BASE = d['base']
        profile = d['profile']
        settings = d['settings']
        settings.update(
            db_path=':memory:',
            backup_base_dir=BASE / 'backup-base-dir-2',
            source_dir=(BASE / 'source-dir').as_posix(),
            included_top_dirs=[BASE / 'source-dir' / 'AA'],
        )
        assert settings.profile == profile
        assert settings.db_path == ':memory:'
        assert settings.backup_base_dir == BASE / 'backup-base-dir-2'
        assert settings.source_dir == BASE / 'source-dir'
        assert settings.included_top_dirs == {BASE / 'source-dir' / 'AA': None}
        with pytest.raises(AttributeError):
            settings.update(this_is_not_a_setting=True)

    def test_ior_dict(self, set_up_data):
        d = set_up_data
        BASE = d['base']
        profile = d['profile']
        settings = d['settings']
        settings |= dict(
            db_path=Path('/tmp/updated-rumar-db-path.sqlite'),
            backup_base_dir=(BASE / 'backup-base-dir-3').as_posix(),
            source_dir=BASE / 'source-dir-2',
            included_top_dirs=['AA', 'B'],
        )
        settings.update()
        assert settings.profile == profile
        assert settings.db_path == Path('/tmp/updated-rumar-db-path.sqlite')
        assert settings.backup_base_dir == BASE / 'backup-base-dir-3'
        assert settings.source_dir == BASE / 'source-dir-2'
        assert settings.included_top_dirs == {'AA': None, 'B': None}
        with pytest.raises(AttributeError):
            settings |= dict(this_is_not_a_setting=True)

    def test_ior_settings(self, set_up_data):
        d = set_up_data
        BASE = d['base']
        profile = d['profile']
        settings = d['settings']
        settings |= Settings(
            profile='new-profile-name',
            db_path=':memory:',
            backup_base_dir=(BASE / 'backup-base-dir-3').as_posix(),
            source_dir=BASE / 'source-dir-2',
            included_top_dirs=[BASE / 'source-dir-2' / 'AA', BASE / 'source-dir-2' / 'B'],
        )
        assert settings.profile == 'new-profile-name'
        assert settings.db_path == ':memory:'
        assert settings.backup_base_dir == BASE / 'backup-base-dir-3'
        assert settings.source_dir == BASE / 'source-dir-2'
        assert settings.included_top_dirs == {BASE / 'source-dir-2' / 'AA': None, BASE / 'source-dir-2' / 'B': None}
