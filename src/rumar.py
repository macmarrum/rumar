#!/usr/bin/python3
# rumar – a file-backup utility
# Copyright (C) 2023-2025  macmarrum (at) outlook (dot) ie
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import argparse
import logging
import logging.config
import os
import re
import sqlite3
import sys
import tarfile
import zipfile
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from enum import Enum
from hashlib import blake2b
from io import BufferedIOBase
from os import PathLike
from pathlib import Path
from stat import S_ISDIR, S_ISSOCK, S_ISDOOR, S_ISLNK
from textwrap import dedent
from time import sleep
from typing import Union, Literal, Pattern, Any, Iterable, cast, Generator, override

vi = sys.version_info
assert (vi.major, vi.minor) >= (3, 10), 'expected Python 3.10 or higher'

try:
    import pyzipper
except ImportError:
    pass

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print('use Python version >= 3.11 or install the module "tomli"')
        raise

me = Path(__file__)

DEBUG_11 = 11
DEBUG_12 = 12
DEBUG_13 = 13
DEBUG_14 = 14
DEBUG_15 = 15
DEBUG_16 = RETVAL_16 = 16
DEBUG_17 = METHOD_17 = 17
LEVEL_TO_SHORT = {
    10: '>>',  # DEBUG
    11: '>:',  # DEBUG11
    12: '>:',  # DEBUG12
    13: '>:',  # DEBUG13
    14: '>:',  # DEBUG14
    15: '>:',  # DEBUG15
    16: '>=',  # RETVAL
    17: '>~',  # METHOD
    20: '::',  # INFO
    30: '*=',  # WARNING
    40: '**',  # ERROR
    50: '##'  # CRITICAL
}
SHORT_DEFAULT = '->'

logging.addLevelName(DEBUG_11, 'DEBUG_11')
logging.addLevelName(DEBUG_12, 'DEBUG_12')
logging.addLevelName(DEBUG_13, 'DEBUG_13')
logging.addLevelName(DEBUG_14, 'DEBUG_14')
logging.addLevelName(DEBUG_15, 'DEBUG_15')
logging.addLevelName(DEBUG_16, 'DEBUG_16')
logging.addLevelName(DEBUG_17, 'DEBUG_17')

logging_funcName_format_width = 25


def log_record_factory(name, level, fn, lno, msg, args, exc_info, func=None, sinfo=None, **kwargs):
    """Add 'levelShort' field to LogRecord, to be used in 'format'"""
    log_record = logging.LogRecord(name, level, fn, lno, msg, args, exc_info, func, sinfo, **kwargs)
    log_record.levelShort = LEVEL_TO_SHORT.get(level, SHORT_DEFAULT)
    log_record.funcNameComplementSpace = ' ' * max(logging_funcName_format_width - len(func), 0) if func else ''
    return log_record


logging.setLogRecordFactory(log_record_factory)


def get_default_path(suffix: str) -> Path:
    """Returns the same name but with the provided suffix, located in the same directory as the program.
    If not found, checks in %APPDATA%/ or $XDG_CONFIG_HOME/{path.stem}/.
    If not found, falls back to the first option.
    """
    name = me.with_suffix(suffix).name
    path = me.parent / name
    if path.exists():
        return path
    else:
        path_alt = get_appdata() / me.stem / name
        if path_alt.exists():
            return path_alt
        else:
            return path


def get_appdata() -> Path:
    if os.name == 'nt':
        return Path(os.environ['APPDATA'])
    elif os.name == 'posix':
        return Path(os.environ.get('XDG_CONFIG_HOME', '~/.config')).expanduser()
    else:
        raise RuntimeError(f"unknown os.name: {os.name}")


LOGGING_TOML_DEFAULT = '''\
version = 1

[formatters.f1]
format = "{levelShort} {asctime} {funcName}:{funcNameComplementSpace} {msg}"
style = "{"
validate = true

[handlers.to_console]
class = "logging.StreamHandler"
formatter = "f1"
#level = "DEBUG_14"

[handlers.to_file]
class = "logging.FileHandler"
filename = "rumar.log"
encoding = "UTF-8"
formatter = "f1"
#level = "DEBUG_14"

[loggers.rumar]
handlers = [
    "to_console",
    "to_file",
]
level = "DEBUG_14"
'''

rumar_logging_toml_path = get_default_path(suffix='.logging.toml')
if rumar_logging_toml_path.exists():
    # print(f":: loading logging config from {rumar_logging_toml_path}")
    dict_config = tomllib.load(rumar_logging_toml_path.open('rb'))
else:
    # print(':: loading default logging config')
    dict_config = tomllib.loads(LOGGING_TOML_DEFAULT)
logging.config.dictConfig(dict_config)
logger = logging.getLogger('rumar')

store_true = 'store_true'
PathAlike = Union[str, PathLike[str]]
UTF8 = 'UTF-8'
RUMAR_SQLITE = 'rumar.sqlite'
RX_ARCHIVE_SUFFIX = re.compile(r'(\.(?:tar(?:\.(?:gz|bz2|xz))?|zipx))$')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--toml', type=mk_abs_path, default=get_default_path(suffix='.toml'),
                        help=('path to settings; '
                              'by default rumar.toml in the same directory as rumar.py or in %%APPDIR%%\\rumar\\ (on NT), ${XDG_CONFIG_HOME:-$HOME/.config}/rumar/ (on POSIX)'))
    subparsers = parser.add_subparsers(dest='action', required=True, help='actions work on profile(s) defined in settings (TOML)')
    # list profiles
    parser_list = subparsers.add_parser('list-profiles', aliases=['l'],
                                        help='list profiles')
    parser_list.set_defaults(func=list_profiles)
    add_profile_args_to_parser(parser_list, required=False)
    # create
    parser_create = subparsers.add_parser(Command.CREATE.value, aliases=['c'],
                                          help='create a backup of each file that matches profile criteria, if the file changed')
    parser_create.set_defaults(func=create)
    add_profile_args_to_parser(parser_create, required=True)
    # extract
    parser_extract = subparsers.add_parser(Command.EXTRACT.value, aliases=['x'],
                                           help='extract [to source_dir | --target-dir] the latest backup of each file [in backup_base_dir_for_profile | --archive-dir]')
    parser_extract.set_defaults(func=extract)
    add_profile_args_to_parser(parser_extract, required=True)
    parser_extract.add_argument('--top-archive-dir', type=Path,
                                help='path to a top directory from which to extract the latest backups, recursively; all other backups in backup_base_dir_for_profile are ignored')
    parser_extract.add_argument('--directory', '-C', type=mk_abs_path,
                                help="path to the base directory used for extraction; profile's source_dir by default")
    parser_extract.add_argument('--overwrite', action=store_true,
                                help="overwrite target files without asking")
    parser_extract.add_argument('--meta-diff', action=store_true,
                                help="overwrite target files without asking if mtime or size differ between backup and target")
    # sweep
    parser_sweep = subparsers.add_parser(Command.SWEEP.value, aliases=['s'],
                                         help='sweep old backups that match profile criteria')
    parser_sweep.set_defaults(func=sweep)
    parser_sweep.add_argument('-d', '--dry-run', action=store_true)
    add_profile_args_to_parser(parser_sweep, required=True)
    args = parser.parse_args()
    # pass args to the appropriate function
    args.func(args)


def add_profile_args_to_parser(parser: argparse.ArgumentParser, required: bool):
    profile_gr = parser.add_mutually_exclusive_group(required=required)
    profile_gr.add_argument('-a', '--all-profiles', action=store_true)
    profile_gr.add_argument('-p', '--profile', nargs='+')


def mk_abs_path(file_path: str) -> Path:
    return Path(file_path).expanduser().absolute()


def list_profiles(args):
    profile_to_settings = make_profile_to_settings_from_toml_path(args.toml)
    for profile, settings in profile_to_settings.items():
        if args.profile and profile not in args.profile:
            continue
        print(f"{settings}")


def create(args):
    profile_to_settings = make_profile_to_settings_from_toml_path(args.toml)
    rumar = Rumar(profile_to_settings)
    if args.all_profiles:
        rumar.create_for_all_profiles()
    elif args.profile:
        for profile in args.profile:
            rumar.create_for_profile(profile)


def extract(args):
    profile_to_settings = make_profile_to_settings_from_toml_path(args.toml)
    rumar = Rumar(profile_to_settings)
    if args.all_profiles:
        rumar.extract_for_all_profiles(args.top_archive_dir, args.directory, args.overwrite, args.meta_diff)
    elif args.profile:
        for profile in args.profile:
            rumar.extract_for_profile(profile, args.top_archive_dir, args.directory, args.overwrite, args.meta_diff)


def sweep(args):
    profile_to_settings = make_profile_to_settings_from_toml_path(args.toml)
    broom = Broom(profile_to_settings)
    is_dry_run = args.dry_run or False
    if args.all_profiles:
        broom.sweep_all_profiles(is_dry_run=is_dry_run)
    elif args.profile:
        for profile in args.profile:
            broom.sweep_profile(profile, is_dry_run=is_dry_run)


class RumarFormat(Enum):
    TAR = 'tar'
    TGZ = 'tar.gz'
    TBZ = 'tar.bz2'
    TXZ = 'tar.xz'
    # zipx is experimental
    ZIPX = 'zipx'


class Command(Enum):
    CREATE = 'create'
    EXTRACT = 'extract'
    SWEEP = 'sweep'


@dataclass
class Settings:
    r"""
    profile: str
      name of the profile
    backup_base_dir: str
      used by: create, sweep
      path to the base directory used for backup; usually set in the global space, common for all profiles
      backup dir for each profile is constructed as _**backup_base_dir**_ + _**profile**_, unless _**backup_base_dir_for_profile**_ is set, which takes precedence
    backup_base_dir_for_profile: str
      used by: create, extract, sweep
      path to the base dir used for the profile; usually left unset; see _**backup_base_dir**_
    archive_format: Literal['tar', 'tar.gz', 'tar.bz2', 'tar.xz'] = 'tar.gz'
      used by: create, sweep
      format of archive files to be created
    compression_level: int = 3
      used by: create
      for the formats 'tar.gz', 'tar.bz2', 'tar.xz': compression level from 0 to 9
    no_compression_suffixes_default: str = '7z,zip,zipx,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,cbz,png,jpg,gif,mp4,mov,avi,mp3,m4a,aac,ogg,ogv,kdbx'
      used by: create
      comma-separated string of lower-case suffixes for which to use uncompressed tar
    no_compression_suffixes: str = ''
      used by: create
      extra lower-case suffixes in addition to _**no_compression_suffixes_default**_
    tar_format: Literal[0, 1, 2] = 1 (tarfile.GNU_FORMAT)
      used by: create
      see also https://docs.python.org/3/library/tarfile.html#supported-tar-formats and https://www.gnu.org/software/tar/manual/html_section/Formats.html
    source_dir: str
      used by: create, extract
      path to the directory which is to be archived
    included_top_dirs: list[str]
      used by: create, sweep
      a list of top-directory paths
      if present, only files from those dirs and their descendant subdirs will be considered, together with _**included_files_as_glob**_
      the paths can be relative to _**source_dir**_ or absolute, but always under _**source_dir**_
      absolute paths start with a root (`/` or `{drive}:\`), unlike relative paths
      if missing, _**source_dir**_ and all its descendant subdirs will be considered
    excluded_top_dirs: list[str]
      used by: create, sweep
      like _**included_top_dirs**_, but for exclusion
      a list of paths under any of _**included_top_dirs**_, that are to be excluded
      e.g. included_top_dirs = ['Project1', 'Project3']; excluded_top_dirs = ['Project1/Vision/Pictures']
    included_dirs_as_regex: list[str]
      used by: create, sweep
      a list of regex patterns, applied after _**..._top_dirs**_ and dirnames of _**..._files_as_glob**_
      if present, only matching directories will be included
      `/` must be used as the path separator, also on MS Windows
      the patterns are matched against a path relative to _**source_dir**_
      the first segment in the relative path (to match against) also starts with a slash
      e.g. `['/B$',]` will match any basename equal to `B`, at any level
      regex-pattern matching is case-sensitive – use `(?i)` at each pattern's beginning for case-insensitive matching
      see also https://docs.python.org/3/library/re.html
    excluded_dirs_as_regex: list[str]
      used by: create, sweep
      like _**included_dirs_as_regex**_, but for exclusion
    included_files_as_glob: list[str]
      used by: create, sweep
      a list of glob patterns, also known as shell-style wildcards, i.e. `* ? [seq] [!seq]`
      if present, only matching files will be considered, together with files from _**included_top_dirs**_
      the paths/globs can be partial, relative to _**source_dir**_ or absolute, but always under _**source_dir**_
      e.g. `['My Music\*.m3u']`
      on MS Windows, global-pattern matching is case-insensitive
      caution: a leading path separator in a path/glob indicates a root directory, e.g. `['\My Music\*']`
      means `C:\My Music\*` or `D:\My Music\*` but not `C:\Users\Mac\Documents\My Music\*`
      see also https://docs.python.org/3/library/fnmatch.html and https://en.wikipedia.org/wiki/Glob_(programming)
    excluded_files_as_glob: list[str]
      used by: create, sweep
      like _**included_files_as_glob**_, but for exclusion
    included_files_as_regex: list[str]
      used by: create, sweep
      like _**included_dirs_as_regex**_, but for files
      applied after _**..._top_dirs**_ and _**..._dirs_as_regex**_ and _**..._files_as_glob**_
    excluded_files_as_regex: list[str]
      used by: create, sweep
      like _**included_files_as_regex**_, but for exclusion
    checksum_comparison_if_same_size: bool = False
      used by: create
      when False, a file is considered changed if its mtime is later than the latest backup's mtime and its size changed
      when True, BLAKE2b checksum is calculated to determine if the file changed despite having the same size
      _mtime := time of last modification_
      see also https://en.wikipedia.org/wiki/File_verification
    file_deduplication: bool = False
      used by: create
      when True, an attempt is made to find and skip duplicates
      a duplicate file has the same suffix and size and part of its name, case-insensitive (suffix, name)
    min_age_in_days_of_backups_to_sweep: int = 2
      used by: sweep
      only the backups which are older than the specified number of days are considered for removal
    number_of_backups_per_day_to_keep: int = 2
      used by: sweep
      for each file, the specified number of backups per day is kept, if available
      more backups per day might be kept to satisfy _**number_of_backups_per_week_to_keep**_ and/or _**number_of_backups_per_month_to_keep**_
      oldest backups are removed first
    number_of_backups_per_week_to_keep: int = 14
      used by: sweep
      for each file, the specified number of backups per week is kept, if available
      more backups per week might be kept to satisfy _**number_of_backups_per_day_to_keep**_ and/or _**number_of_backups_per_month_to_keep**_
      oldest backups are removed first
    number_of_backups_per_month_to_keep: int = 60
      used by: sweep
      for each file, the specified number of backups per month is kept, if available
      more backups per month might be kept to satisfy _**number_of_backups_per_day_to_keep**_ and/or _**number_of_backups_per_week_to_keep**_
      oldest backups are removed first
    commands_which_use_filters: list[str] = ['create']
      used by: create, sweep
      determines which commands can use the filters specified in the included_* and excluded_* settings
      by default, filters are used only by _**create**_, i.e. _**sweep**_ considers all created backups (no filter is applied)
      a filter for _**sweep**_ could be used to e.g. never remove backups from the first day of a month:
      `excluded_files_as_regex = ['/\d\d\d\d-\d\d-01_\d\d,\d\d,\d\d(\.\d{6})?[+-]\d\d,\d\d~\d+(~.+)?\.tar(\.(gz|bz2|xz))?$']`
      it's best when the setting is part of a separate profile, i.e. a copy made for _**sweep**_,
      otherwise _**create**_ will also seek such files to be excluded
    db_path: str = _**backup_base_dir**_/rumar.sqlite
    """
    SUFFIXES_SEP: str = field(default=',', init=False, repr=False)
    profile: str
    backup_base_dir: Union[str, Path]
    source_dir: Union[str, Path]
    backup_base_dir_for_profile: Path | str | None = None
    included_top_dirs: Union[set[Path], list[str]] = field(default_factory=list)
    excluded_top_dirs: Union[set[Path], list[str]] = field(default_factory=list)
    included_dirs_as_regex: Union[list[Pattern], list[str]] = field(default_factory=list)
    excluded_dirs_as_regex: Union[list[Pattern], list[str]] = field(default_factory=list)
    included_files_as_glob: Union[set[str], list[str]] = field(default_factory=list)
    excluded_files_as_glob: Union[set[str], list[str]] = field(default_factory=list)
    included_files_as_regex: Union[list[Pattern], list[str]] = field(default_factory=list)
    excluded_files_as_regex: Union[list[Pattern], list[str]] = field(default_factory=list)
    archive_format: Union[RumarFormat, str] = RumarFormat.TGZ
    # password for zipx, as it's AES-encrypted
    password: bytes | str | None = None
    zip_compression_method: int = zipfile.ZIP_DEFLATED
    compression_level: int = 3
    no_compression_suffixes_default: str = (
        '7z,zip,zipx,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,'
        'xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,cbz,'
        'png,jpg,gif,mp4,mov,avi,mp3,m4a,aac,ogg,ogv,kdbx'
    )
    no_compression_suffixes: str = ''
    tar_format: Literal[0, 1, 2] = tarfile.GNU_FORMAT
    checksum_comparison_if_same_size: bool = False
    file_deduplication: bool = False
    min_age_in_days_of_backups_to_sweep: int = 2
    number_of_backups_per_day_to_keep: int = 2
    number_of_backups_per_week_to_keep: int = 14
    number_of_backups_per_month_to_keep: int = 60
    commands_which_use_filters: Union[list[str], tuple[Command, ...]] = (Command.CREATE,)
    db_path: Path | str | None = None

    @staticmethod
    def is_each_elem_of_type(lst: list, typ: Union[Any, tuple]) -> bool:
        return all(isinstance(elem, typ) for elem in lst)

    def __post_init__(self):
        self._pathlify('source_dir')
        self._pathlify('backup_base_dir')
        if self.backup_base_dir_for_profile:
            self._pathlify('backup_base_dir_for_profile')
        else:
            self.backup_base_dir_for_profile = self.backup_base_dir / self.profile
        self._absolutopathosetify('included_top_dirs')
        self._setify('included_files_as_glob')
        self._absolutopathosetify('excluded_top_dirs')
        self._setify('excluded_files_as_glob')
        self._patternify('included_dirs_as_regex')
        self._patternify('included_files_as_regex')
        self._patternify('excluded_dirs_as_regex')
        self._patternify('excluded_files_as_regex')
        self.suffixes_without_compression = {f".{s}" for s in self.SUFFIXES_SEP.join([self.no_compression_suffixes_default, self.no_compression_suffixes]).split(self.SUFFIXES_SEP) if s}
        # https://stackoverflow.com/questions/71846054/-cast-a-string-to-an-enum-during-instantiation-of-a-dataclass-
        if self.archive_format is None:
            self.archive_format = RumarFormat.TGZ
        self.archive_format = RumarFormat(self.archive_format)
        self.commands_which_use_filters = tuple(Command(cmd) for cmd in self.commands_which_use_filters)
        try:  # make sure password is bytes
            self.password = self.password.encode(UTF8)
        except AttributeError:  # 'bytes' object has no attribute 'encode'
            pass
        if self.db_path is None:
            self.db_path = self.backup_base_dir / RUMAR_SQLITE

    def _setify(self, attribute_name: str):
        attr = getattr(self, attribute_name)
        if attr is None:
            setattr(self, attribute_name, set())
        setattr(self, attribute_name, set(attr))

    def _absolutopathosetify(self, attribute_name: str):
        attr = getattr(self, attribute_name)
        if attr is None:
            setattr(self, attribute_name, set())
        lst = []
        for elem in attr:
            p = Path(elem)
            if not p.is_absolute():
                lst.append(self.source_dir / p)
            else:
                if not p.as_posix().startswith(self.source_dir.as_posix()):
                    raise ValueError(f"{attribute_name}: {p} is not under {self.source_dir}!")
                lst.append(p)
        setattr(self, attribute_name, set(lst))

    def _pathlify(self, attribute_name: str):
        attr = getattr(self, attribute_name)
        if not attr:
            return
        if isinstance(attr, list):
            if not self.is_each_elem_of_type(attr, Path):
                setattr(self, attribute_name, [Path(elem) for elem in attr])
        else:
            if not isinstance(attr, Path):
                setattr(self, attribute_name, Path(attr))

    def _patternify(self, attribute_name: str):
        attr = getattr(self, attribute_name)
        if not attr:
            return
        if not isinstance(attr, list):
            raise TypeError(f"expected a list of values, got {attr!r}")
        setattr(self, attribute_name, [re.compile(elem) for elem in attr])

    def __str__(self):
        return ("{"
                f"profile: {self.profile!r}, "
                f"backup_base_dir_for_profile: {self.backup_base_dir_for_profile.as_posix()!r}, "
                f"source_dir: {self.source_dir.as_posix()!r}"
                "}")

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                raise AttributeError(f"Settings has no attribute '{key}'")
        self.__post_init__()
        return self

    def __ior__(self, other):
        if isinstance(other, dict):
            self.update(**other)
            return self
        if isinstance(other, type(self)):
            self.update(**{k: getattr(other, k) for k in other.__dataclass_fields__})
            return self
        raise TypeError(f"Unsupported operand type for |=: '{type(self)}' and '{type(other)}'")


ProfileToSettings = dict[str, Settings]


def make_profile_to_settings_from_toml_path(toml_file: Path) -> ProfileToSettings:
    logger.log(DEBUG_11, f"{toml_file=}")
    toml_str = toml_file.read_text(encoding=UTF8)
    return make_profile_to_settings_from_toml_text(toml_str)


def make_profile_to_settings_from_toml_text(toml_str) -> ProfileToSettings:
    profile_to_settings: ProfileToSettings = {}
    toml_dict = tomllib.loads(toml_str)
    verify_and_remove_version(toml_dict)
    common_kwargs_for_settings = {}
    profile_to_dict = {}
    for key, value in toml_dict.items():
        if isinstance(value, dict):  # gather profiles, i.e. "name": {dict, aka hash table}
            if not key.startswith('#'):  # skip profiles starting with hash (#)
                profile_to_dict[key] = value
        else:  # gather top-level settings (common for each profile)
            common_kwargs_for_settings[key] = value
    for profile, dct in profile_to_dict.items():
        kwargs_for_settings = common_kwargs_for_settings.copy()
        kwargs_for_settings['profile'] = profile
        for key, value in dct.items():
            kwargs_for_settings[key] = value
        profile_to_settings[profile] = Settings(**kwargs_for_settings)
    return profile_to_settings


def verify_and_remove_version(toml_dict):
    version = toml_dict.get('version', 'missing')
    if version != 2:
        logger.warning(f"rumar.toml version is {version} - expected `version = 2`")
    if any('sha256_comparison_if_same_size' in dct for dct in toml_dict.values() if isinstance(dct, dict)):
        msg = 'found sha256_comparison_if_same_size - expected checksum_comparison_if_same_size'
        logger.error(msg)
        raise ValueError(msg)
    del toml_dict['version']


class CreateReason(Enum):
    """like in CRUD + INIT (for RumarDB initial state)"""
    CREATE = '+>'
    UPDATE = '~>'
    DELETE = 'x>'
    INIT = '*>'  # for RumarDB


SLASH = '/'
BACKSLASH = '\\'


class Rath(Path):
    """Path with lstat cache.\n
    Overrides:\n
    - lstat()
    - with_segments(): Rath
    These raise TypeError - missing arg `lstat_cache`:\n
    - home()
    - cwd()
    """

    def __init__(self, *args, lstat_cache: dict[Path, os.stat_result]):
        self.lstat_cache = lstat_cache
        super().__init__(*args)

    # @override
    def lstat(self):
        if lstat := self.lstat_cache.get(self):
            return lstat
        else:
            lstat = super().lstat()
            self.lstat_cache[self] = lstat
            return lstat

    # @override
    def with_segments(self, *pathsegments):
        """`Path.with_segments` calls `type(self)(*pathsegments)`\n
        Override it and call `Rath` with lstat_cache\n
        `with_segments` is used by: `joinpath`, `readlink`, `__truediv__`\n
        and via `_from_parsed_string` or `_parts` by: `parent`, `parents`, `iterdir`, `relative_to`, `with_name`;\n
        probably also by: `with_stem`, `with_suffix`, `absolute`, `expanduser`, `resolve` because they return Rath
        """
        return Rath(*pathsegments, lstat_cache=self.lstat_cache)


def iter_all_files(top_path: Rath) -> Generator[Rath, None, None]:
    """
    Note: symlinks to directories are considered files
    :param top_path: usually `s.source_dir` or `s.backup_base_dir_for_profile`
    """
    dir_raths = []
    for rath in top_path.iterdir():
        if S_ISDIR(rath.lstat().st_mode):
            dir_raths.append(rath)
        else:
            yield rath
    for dir_rath in dir_raths:
        yield from iter_all_files(dir_rath)


def iter_matching_files(top_path: Rath, s: Settings) -> Generator[Rath, None, None]:
    """
    Note: symlinks to directories are considered files
    :param top_path: usually `s.source_dir` or `s.backup_base_dir_for_profile`
    """
    inc_dirs_rx = s.included_dirs_as_regex
    exc_dirs_rx = s.excluded_dirs_as_regex
    inc_files_rx = s.included_files_as_regex
    exc_files_rx = s.excluded_files_as_regex

    def _iter_matching_files(directory: Rath) -> Generator[Rath, None, None]:
        dir_raths__skip_files_because_dir_is_higher_level = []
        dir_raths = {}  # to preserve order
        file_raths = {}  # to preserve order
        for rath in directory.iterdir():
            if S_ISDIR(rath.lstat().st_mode):
                dir_rath = rath
                relative_dir_p = derive_relative_p(dir_rath, top_path, with_leading_slash=True)
                is_dir_matching_top_dirs, skip_files_because_dir_is_higher_level = calc_dir_matches_top_dirs(dir_rath, relative_dir_p, s)
                if skip_files_because_dir_is_higher_level:
                    dir_raths__skip_files_because_dir_is_higher_level.append(dir_rath)
                if is_dir_matching_top_dirs:  # matches dirnames and/or top_dirs, now check regex
                    if inc_dirs_rx:  # only included paths must be considered
                        if find_matching_pattern(relative_dir_p, inc_dirs_rx):
                            dir_raths[dir_rath] = None
                        else:
                            logger.log(DEBUG_13, f"|d ...{relative_dir_p}  -- skipping dir (none of included_dirs_as_regex matches)")
                    else:
                        dir_raths[dir_rath] = None
                    if exc_dirs_rx and dir_rath in dir_raths and (exc_rx := find_matching_pattern(relative_dir_p, exc_dirs_rx)):
                        del dir_raths[dir_rath]
                        logger.log(DEBUG_14, f"|d ...{relative_dir_p}  -- skipping dir (matches '{exc_rx}')")
                else:  # doesn't match dirnames and/or top_dirs
                    pass
            else:  # a file
                file_rath = rath
                relative_file_p = derive_relative_p(file_rath, top_path, with_leading_slash=True)
                if is_file_matching_glob(file_rath, relative_file_p, s):  # matches glob, now check regex
                    if inc_files_rx:  # only included paths must be considered
                        if find_matching_pattern(relative_file_p, inc_files_rx):
                            file_raths[file_rath] = None
                        else:
                            logger.log(DEBUG_13, f"|f ...{relative_file_p}  -- skipping (none of included_files_as_regex matches)")
                    else:
                        file_raths[file_rath] = None
                    if exc_files_rx and file_rath in file_raths and (exc_rx := find_matching_pattern(relative_file_p, exc_files_rx)):
                        del file_raths[file_rath]
                        logger.log(DEBUG_14, f"|f ...{relative_file_p}  -- skipping (matches '{exc_rx}')")
                else:  # doesn't match glob
                    pass
        for file_rath in file_raths:
            dir_rath = file_rath.parent
            if dir_rath not in dir_raths__skip_files_because_dir_is_higher_level:
                yield file_rath
        for dir_rath in dir_raths:
            yield from _iter_matching_files(dir_rath)

    yield from _iter_matching_files(top_path)


def calc_dir_matches_top_dirs(dir_path: Path, relative_dir_p: str, s: Settings) -> tuple[bool, bool]:
    """ Returns a tuple: (is_dir_matching_top_dirs, skip_files_because_dirpath_is_higher_level) """
    dir_path_psx = dir_path.as_posix()
    for exc_top_psx in (p.as_posix() for p in s.excluded_top_dirs):
        if dir_path_psx.startswith(exc_top_psx):
            logger.log(DEBUG_14, f"|D ...{relative_dir_p}  -- skipping (matches excluded_top_dirs)")
            return False, False
    if not (s.included_top_dirs or s.included_files_as_glob):
        logger.log(DEBUG_11, f"=D ...{relative_dir_p}  -- including all (no included_top_dirs or included_files_as_glob)")
        return True, False
    # remove the file part by splitting at the rightmost sep, making sure not to split at the root sep
    inc_file_dirnames_as_glob = {f.rsplit(sep, 1)[0]: None for f in s.included_files_as_glob if (sep := find_sep(f)) and sep in f.lstrip(sep)}
    for dirname_glob in inc_file_dirnames_as_glob:
        if dir_path.match(dirname_glob):
            logger.log(DEBUG_12, f"=D ...{relative_dir_p}  -- matches included_file_as_glob's dirname")
            return True, False
    for inc_top_psx in (p.as_posix() for p in s.included_top_dirs):
        # Example
        # source_dir = '/home'
        # included_top_dirs = ['/home/docs', '/home/pics']
        if dir_path_psx.startswith(inc_top_psx):
            # current dir_path_psx = '/home/docs/med'
            # '/home/docs/med'.startswith('/home/docs')
            logger.log(DEBUG_12, f"=D ...{relative_dir_p}  -- matches included_top_dirs")
            return True, False
        if inc_top_psx.startswith(dir_path_psx):
            # current dir_path_psx = '/home'
            # '/home/docs'.startswith('/home')
            # this is to keep the path in dirs of os.walk(), i.e. to avoid excluding the entire tree
            # but not for files, i.e. files in '/home' must be skipped
            # no logging - dir_path is included for technical reasons only
            return True, True  # skip_files_because_dir_is_higher_level
    logger.log(DEBUG_13, f"|D ...{relative_dir_p}  -- skipping (doesn't match dirnames and/or top_dirs)")
    return False, False


def is_file_matching_glob(file_path: Path, relative_p: str, s: Settings) -> bool:
    # interestingly, the following expression doesn't have the same effect as the below for-loops - why?
    # not any(file_path.match(file_as_glob) for file_as_glob in exc_files) and (
    #         any(file_path.match(file_as_glob) for file_as_glob in inc_files)
    #         or any(file_path_psx.startswith(top_dir) for top_dir in inc_top_dirs_psx)
    # )
    for file_as_glob in s.excluded_files_as_glob:
        if file_path.match(file_as_glob):
            logger.log(DEBUG_14, f"|F ...{relative_p}  -- skipping (matches excluded_files_as_glob {file_as_glob!r})")
            return False
    if not (s.included_top_dirs or s.included_files_as_glob):
        logger.log(DEBUG_11, f"=F ...{relative_p}  -- including all (no included_top_dirs or included_files_as_glob)")
        return True
    for file_as_glob in s.included_files_as_glob:
        if file_path.match(file_as_glob):
            logger.log(DEBUG_12, f"=F ...{relative_p}  -- matches included_files_as_glob {file_as_glob!r}")
            return True
    file_path_psx = file_path.as_posix()
    for inc_top_psx_ in (p.as_posix() + '/' for p in s.included_top_dirs):
        if file_path_psx.startswith(inc_top_psx_):
            logger.log(DEBUG_12, f"=F ...{relative_p}  -- matches included_top_dirs {inc_top_psx_!r}")
            return True
    logger.log(DEBUG_13, f"|F ...{relative_p}  -- skipping file (doesn't match top dir or file glob)")
    return False


def find_sep(g: str) -> str:
    """
    included_files_as_glob can use a slash or a backslash as a path separator
    :return the path separator which is used
    :raise ValueError if both backslash and slash are found in the glob
    """
    msg = 'Found both a backslash and a slash in `{}` - expected either one or the other'
    sep = None
    if SLASH in g:
        sep = SLASH
        if BACKSLASH in g:
            raise ValueError(msg.format(g))
    elif BACKSLASH in g:
        sep = BACKSLASH
    return sep


def derive_relative_p(path: Path, base_dir: Path, with_leading_slash=False) -> str:
    path_psx = path.as_posix()
    base_dir_psx = base_dir.as_posix()
    if not path_psx.startswith(base_dir_psx):
        raise ValueError(f"{str(path)} doesn't start with {str(base_dir)}")
    relative_p = path_psx.removeprefix(base_dir_psx)
    return relative_p.removeprefix(SLASH) if not with_leading_slash else relative_p


def find_matching_pattern(relative_p: str, patterns: list[Pattern]):
    # logger.debug(f"{relative_p}, {[p.pattern for p in patterns]}")
    for rx in patterns:
        if rx.search(relative_p):
            return rx.pattern
    return None


def sorted_files_by_stem_then_suffix_ignoring_case(matching_files: Iterable[Path]):
    """sort by stem then suffix, i.e. 'abc.txt' before 'abc(2).txt'; ignore case"""
    return sorted(matching_files, key=lambda x: (x.stem.lower(), x.suffix.lower()))


def compose_archive_path(archive_dir: Path, archive_format: RumarFormat, mtime_str: str, size: int, comment: str | None = None) -> Path:
    return archive_dir / f"{mtime_str}{Rumar.MTIME_SEP}{size}{Rumar.MTIME_SEP + comment if comment else Rumar.BLANK}.{archive_format.value}"


class Rumar:
    """
    Creates a directory named as the original file, containing a TARred copy of the file, optionally compressed.
    Files are added to the TAR archive only if they were changed (mtime, size), as compared to the last archive.
    The directory containing TAR files is placed in a mirrored directory hierarchy.
    """
    BLANK = ''
    RX_NONE = re.compile('')
    MTIME_SEP = '~'
    COLON = ':'
    COMMA = ','
    T = 'T'
    UNDERSCORE = '_'
    DOT_TAR = '.tar'
    DOT_ZIPX = '.zipx'
    SYMLINK_COMPRESSLEVEL = 3
    COMPRESSLEVEL = 'compresslevel'
    COMPRESSION = 'compression'
    PRESET = 'preset'
    SYMLINK_FORMAT_COMPRESSLEVEL = RumarFormat.TGZ, {COMPRESSLEVEL: SYMLINK_COMPRESSLEVEL}
    NOCOMPRESSION_FORMAT_COMPRESSLEVEL = RumarFormat.TAR, {}
    LNK = 'LNK'
    ARCHIVE_FORMAT_TO_MODE = {RumarFormat.TAR: 'x', RumarFormat.TGZ: 'x:gz', RumarFormat.TBZ: 'x:bz2', RumarFormat.TXZ: 'x:xz'}
    CHECKSUM_SUFFIX = '.b2'
    CHECKSUM_SIZE_THRESHOLD = 10_000_000
    STEMS = 'stems'
    RATHS = 'paths'

    def __init__(self, profile_to_settings: ProfileToSettings):
        self._profile_to_settings = profile_to_settings
        self._profile: str | None = None
        self._suffix_size_stems_and_raths: dict[str, dict[int, dict]] = {}
        self.lstat_cache: dict[Path, os.stat_result] = {}
        self._warnings = []
        self._errors = []
        self._rdb: RumarDB = None  # initiated per profile in _at_beginning to support db_path per profile

    @staticmethod
    def should_ignore_for_archive(lstat: os.stat_result) -> bool:
        mode = lstat.st_mode
        return S_ISSOCK(mode) or S_ISDOOR(mode)

    @staticmethod
    def compute_checksum_of_file_in_archive(archive: Path, password: bytes) -> str | None:
        if Rumar.derive_stem(archive.name).endswith(f"~{Rumar.LNK}"):
            return None
        if archive.suffix == Rumar.DOT_ZIPX:
            with pyzipper.AESZipFile(archive) as zf:
                zf.setpassword(password)
                zip_info = zf.infolist()[0]
                with zf.open(zip_info) as f:
                    return compute_blake2b_checksum(f)
        else:
            with tarfile.open(archive) as tf:
                member = tf.getmembers()[0]
                with tf.extractfile(member) as f:
                    return compute_blake2b_checksum(f)

    @staticmethod
    def set_mtime(target_path: Path, mtime: datetime):
        try:
            os.utime(target_path, (0, mtime.timestamp()))
        except:
            logger.error(f">> error setting mtime -> {sys.exc_info()}")

    @classmethod
    def calc_mtime_str(cls, dt: datetime) -> str:
        """archive-file stem - first part"""
        return dt.astimezone().isoformat(sep=cls.UNDERSCORE).replace(cls.COLON, cls.COMMA)

    @classmethod
    def calc_mtime_dt(cls, mtime_str: str) -> datetime:
        return datetime.fromisoformat(mtime_str.replace(cls.COMMA, cls.COLON))

    @classmethod
    def compose_checksum_file_path(cls, archive_path: Path) -> Path:
        stem = cls.derive_stem(archive_path.name)
        return archive_path.with_name(f"{stem}{cls.CHECKSUM_SUFFIX}")

    @classmethod
    def derive_mtime_size(cls, archive_path: Path | None) -> tuple[str, int] | None:
        if archive_path is None:
            return None
        stem = cls.derive_stem(archive_path.name)
        return cls.split_mtime_size(stem)

    @staticmethod
    def derive_stem(basename: str) -> str:
        """Example: 2023-04-30_09,48,20.872144+02,00~123#a7b6de.tar.gz => 2023-04-30_09,48,20+02,00~123#a7b6de"""
        stem = RX_ARCHIVE_SUFFIX.sub('', basename)
        if stem == basename:
            raise RuntimeError('basename: ' + basename)
        return stem

    @staticmethod
    def split_ext(basename: str) -> tuple[str, str]:
        """Example: 2023-04-30_09,48,20.872144+02,00~123.tar.gz => 2023-04-30_09,48,20+02,00~123 .tar.gz"""
        cor_ext_rest = RX_ARCHIVE_SUFFIX.split(basename)
        if len(cor_ext_rest) < 3:
            raise ValueError(basename)
        return cor_ext_rest[0], cor_ext_rest[1]

    @classmethod
    def split_mtime_size(cls, stem: str) -> tuple[str, int]:
        """Example: 2023-04-30_09,48,20.872144+02,00~123~ab12~LNK => 2023-04-30_09,48,20.872144+02,00 123 ab12 LNK"""
        split_result = stem.split(cls.MTIME_SEP)
        mtime_str = split_result[0]
        size = int(split_result[1])
        return mtime_str, size

    def compose_archive_path(self, archive_dir: Path, mtime_str: str, size: int, comment: str | None = None) -> Path:
        return compose_archive_path(archive_dir, self.s.archive_format, mtime_str, size, comment)

    @property
    def s(self) -> Settings:
        return self._profile_to_settings[self._profile]

    def create_for_all_profiles(self):
        for profile in self._profile_to_settings:
            self.create_for_profile(profile)

    def create_for_profile(self, profile: str):
        """Create a backup for the specified profile
        """
        logger.info(f"{profile=}")
        self._at_beginning(profile)
        errors = []
        for d in [self.s.source_dir, self.s.backup_base_dir]:
            if ex := try_to_iterate_dir(d):
                errors.append(str(ex))
        if errors:
            logger.warning(f"SKIP {profile} - {'; '.join(errors)}")
            return
        for rath in self.source_files:
            relative_p = derive_relative_p(rath, self.s.source_dir)
            lstat = rath.lstat()  # don't follow symlinks - pathlib calls stat for each is_*()
            mtime = lstat.st_mtime
            mtime_dt = datetime.fromtimestamp(mtime).astimezone()
            mtime_str = self.calc_mtime_str(mtime_dt)
            size = lstat.st_size
            archive_dir = self.compose_archive_container_dir(relative_p=relative_p)
            # TODO handle LNK target changes, don't blake2b LNKs
            # latest_archive = find_last_file_in_dir(archive_dir, RX_ARCHIVE_SUFFIX)
            latest_archive = self._rdb.get_latest_archive_for_source(relative_p)
            if latest_archive is None:
                # no previous backup found
                self._create(CreateReason.CREATE, rath, relative_p, archive_dir, mtime_str, size, checksum=None)
            else:
                latest_mtime_str, latest_size = self.derive_mtime_size(latest_archive)
                latest_mtime_dt = self.calc_mtime_dt(latest_mtime_str)
                is_changed = False
                if mtime_dt > latest_mtime_dt:
                    if size != latest_size:
                        is_changed = True
                        checksum = None
                    else:
                        is_changed = False
                        if self.s.checksum_comparison_if_same_size:
                            with rath.open('rb') as f:
                                checksum = compute_blake2b_checksum(f)
                            latest_checksum = self._get_archive_checksum(latest_archive)
                            logger.info(f':- {relative_p}  {latest_mtime_str}  {latest_checksum}')
                            is_changed = checksum != latest_checksum
                        # else:  # newer mtime, same size, not instructed to do checksum comparison => no backup
                if is_changed:
                    # file has changed as compared to the last backup
                    logger.info(f":= {relative_p}  {latest_mtime_str}  {latest_size} =: last backup")
                    self._create(CreateReason.UPDATE, rath, relative_p, archive_dir, mtime_str, size, checksum)
                else:
                    self._rdb.save_unchanged(relative_p)
        self._at_end()

    def _at_beginning(self, profile: str):
        self._profile = profile  # for self.s to work
        self.lstat_cache.clear()
        self._warnings.clear()
        self._errors.clear()
        self._rdb = RumarDB(self._profile, self.s)

    def _at_end(self):
        self._rdb.identify_and_save_deleted()
        self._rdb.close_db()
        self._profile = None  # safeguard so that self.s will complain
        if self._warnings:
            for w in self._warnings:
                logger.warning(w)
        if self._errors:
            for e in self._errors:
                logger.error(e)
        self._rdb.close()

    def _get_archive_checksum(self, archive_path: Path):
        """Gets checksum from .b2 file or from RumarDB. Removes .b2 if zero-size"""
        if not (latest_checksum := self._rdb.get_blake2b_checksum(archive_path)):
            checksum_file = self.compose_checksum_file_path(archive_path)
            try:
                st = checksum_file.stat()
            except OSError:  # includes FileNotFoundError, PermissionError
                latest_checksum = self.compute_checksum_of_file_in_archive(archive_path, self.s.password)
            else:  # no exception
                if st.st_size > 0:
                    latest_checksum = checksum_file.read_text()
                    # transfer blake2b checksum from .b2 to RumarDB
                    self._rdb.set_blake2b_checksum(archive_path, latest_checksum)
                else:
                    with suppress(OSError):
                        checksum_file.unlink()
                        logger.debug(f':- remove {str(checksum_file)}')
        return latest_checksum

    def _save_checksum_if_big(self, size, checksum, relative_p, archive_dir, mtime_str):
        """Save checksum if file is big, to save computation time in the future.
        The checksum might not be needed, therefore the cost/benefit ration needs to be considered, i.e.
        whether it's better to save an already computed checksum to disk (time to save it and delete it in the future),
        or -- when the need arises -- to unpack the file and calculate its checksum on the fly (time to read, decompress and checksum).
        On a modern computer with an SDD, this is how long it takes to
         (1) read and decompress an AES-encrypted ZIP_DEFLATED .zipx file (random data) and compute its blake2b checksum;
         (2) read the (uncompressed) file from disk, compute its blake2b checksum and save it to a file
          -- it's assumed the time to save it is similar to the time to read and delete the file in the future
         | size    | (1)  | (2)  |
         |   25 MB | 0.14 | 0.04 |
         |   50 MB | 0.29 | 0.07 |
         |  100 MB | 0.56 | 0.14 |
         |  250 MB | 1.39 | 0.35 |
         |  500 MB | 3.10 | 0.68 |
         | 1000 MB | 5.94 | 1.66 |
         (1) is the amount of time wasted in case it turns out that the checksum is needed (and it wasn't saved before)
         The same test, but on a xml (.mm) file
         | size    | (1)  | (2)  |
         |   10 MB | 0.05 | 0.02 |
        """
        if size > self.CHECKSUM_SIZE_THRESHOLD:
            checksum_file = archive_dir / f"{mtime_str}{self.MTIME_SEP}{size}{self.CHECKSUM_SUFFIX}"
            logger.info(f':  {relative_p}  {checksum}')
            archive_dir.mkdir(parents=True, exist_ok=True)
            checksum_file.write_text(checksum)

    def _create(self, create_reason: CreateReason, rath: Rath, relative_p: str, archive_dir: Path, mtime_str: str, size: int, checksum: str | None):
        if self.s.archive_format == RumarFormat.ZIPX:
            self._create_zipx(create_reason, rath, relative_p, archive_dir, mtime_str, size, checksum)
        else:
            self._create_tar(create_reason, rath, relative_p, archive_dir, mtime_str, size, checksum)

    def _create_tar(self, create_reason: CreateReason, rath: Rath, relative_p: str, archive_dir: Path, mtime_str: str, size: int, checksum: str | None):
        archive_dir.mkdir(parents=True, exist_ok=True)
        sign = create_reason.value
        reason = create_reason.name
        logger.info(f"{sign} {relative_p}  {mtime_str}  {size} {reason} {archive_dir}")
        archive_format, compresslevel_kwargs = self.calc_archive_format_and_compresslevel_kwargs(rath)
        mode = self.ARCHIVE_FORMAT_TO_MODE[archive_format]
        is_lnk = S_ISLNK(rath.lstat().st_mode)
        archive_path = self.compose_archive_path(archive_dir, mtime_str, size, self.LNK if is_lnk else self.BLANK)
        with tarfile.open(archive_path, mode, format=self.s.tar_format, **compresslevel_kwargs) as tf:
            tf.add(rath, arcname=rath.name)
        self._rdb.save(create_reason, relative_p, archive_path, checksum)

    def _create_zipx(self, create_reason: CreateReason, rath: Rath, relative_p: str, archive_dir: Path, mtime_str: str, size: int, checksum: str | None):
        archive_dir.mkdir(parents=True, exist_ok=True)
        sign = create_reason.value
        reason = create_reason.name
        logger.info(f"{sign} {relative_p}  {mtime_str}  {size} {reason} {archive_dir}")
        if rath.suffix.lower() in self.s.suffixes_without_compression:
            kwargs = {self.COMPRESSION: zipfile.ZIP_STORED}
        else:
            kwargs = {self.COMPRESSION: self.s.zip_compression_method, self.COMPRESSLEVEL: self.s.compression_level}
        is_lnk = S_ISLNK(rath.lstat().st_mode)
        archive_path = self.compose_archive_path(archive_dir, mtime_str, size, self.LNK if is_lnk else self.BLANK)
        with pyzipper.AESZipFile(archive_path, 'w', encryption=pyzipper.WZ_AES, **kwargs) as zf:
            zf.setpassword(self.s.password)
            zf.write(rath, arcname=rath.name)
        self._rdb.save(create_reason, relative_p, archive_path, checksum)

    def compose_archive_container_dir(self, *, relative_p: str | None = None, path: Path | None = None) -> Path:
        assert relative_p or path, '** either relative_p or path must be provided'
        if not relative_p:
            relative_p = derive_relative_p(path, self.s.source_dir)
        return self.s.backup_base_dir_for_profile / relative_p

    def calc_archive_format_and_compresslevel_kwargs(self, rath: Rath) -> tuple[RumarFormat, dict]:
        if (
                rath.is_absolute() and  # for gardner.repack, which has only arc_name
                S_ISLNK(rath.lstat().st_mode)
        ):
            return self.SYMLINK_FORMAT_COMPRESSLEVEL
        elif rath.suffix.lower() in self.s.suffixes_without_compression or self.s.archive_format == RumarFormat.TAR:
            return self.NOCOMPRESSION_FORMAT_COMPRESSLEVEL
        else:
            key = self.PRESET if self.s.archive_format == RumarFormat.TXZ else self.COMPRESSLEVEL
            return self.s.archive_format, {key: self.s.compression_level}

    @property
    def source_files(self):
        return self.make_optionally_deduped_list_of_matching_files()

    def make_optionally_deduped_list_of_matching_files(self):
        s = self.s
        source_dir = s.source_dir
        matching_files = []
        # the make-iterator logic is not extracted to a function so that logger prints the calling function's name
        if Command.CREATE in s.commands_which_use_filters:
            iterator = iter_matching_files(Rath(source_dir, lstat_cache=self.lstat_cache), s)
            logger.debug(f"{s.commands_which_use_filters=} => iter_matching_files")
        else:
            iterator = iter_all_files(Rath(source_dir, lstat_cache=self.lstat_cache))
            logger.debug(f"{s.commands_which_use_filters=} => iter_all_files")
        for file_rath in iterator:
            if self.should_ignore_for_archive(file_rath.lstat()):
                logger.info(f"-| {file_rath}  -- ignoring file for archiving: socket/door")
                continue
            if s.file_deduplication and (duplicate := self.find_duplicate(file_rath)):
                logger.info(f"{derive_relative_p(file_rath, source_dir)!r} -- skipping: duplicate of {derive_relative_p(duplicate, source_dir)!r}")
                continue
            matching_files.append(file_rath)
        return sorted_files_by_stem_then_suffix_ignoring_case(matching_files)

    def find_duplicate(self, file_rath: Rath) -> Rath | None:
        """
        a duplicate file has the same suffix and size and part of its name, case-insensitive (suffix, name)
        """
        stem, suffix = os.path.splitext(file_rath.name.lower())
        size = file_rath.lstat().st_size
        if size_to_stems_and_paths := self._suffix_size_stems_and_raths.get(suffix):
            if stems_and_raths := size_to_stems_and_paths.get(size):
                if stems_and_raths:
                    stems = stems_and_raths[self.STEMS]
                    for index, s in enumerate(stems):
                        if stem in s or s in stem:
                            return stems_and_raths[self.RATHS][index]
        # no put; create one
        stems_and_raths = self._suffix_size_stems_and_raths.setdefault(suffix, {}).setdefault(size, {})
        stems_and_raths.setdefault(self.STEMS, []).append(stem)
        stems_and_raths.setdefault(self.RATHS, []).append(file_rath)
        return None

    def extract_for_all_profiles(self, top_archive_dir: Path | None, directory: Path | None, overwrite: bool, meta_diff: bool):
        for profile in self._profile_to_settings:
            if directory is None:
                directory = self._profile_to_settings[profile].source_dir
            self.extract_for_profile(profile, top_archive_dir, directory, overwrite, meta_diff)

    def extract_for_run(self, run_datetime_iso: str, top_dir: Path | None, directory: Path | None, overwrite: bool, meta_diff: bool):
        """Extract files backed up during a particular run (datetime) as recorded in rumardb

        :param run_datetime_iso:
        :param top_dir: (optional) limit files to be extracted to the top dir; can be relative; in the backup tree if absolute - all files for the run_datetime_iso if missing
        :param directory: (optional) target directory - settings.source_dir if missing
        :param overwrite: whether to overwrite target files without asking
        :param meta_diff: whether to overwrite target files without asking if mtime or size differ between backup and target
        """
        run_present = self._rdb.is_run_present(run_datetime_iso)
        profile = dict(self._rdb.get_run_datetime_isos()).get(run_datetime_iso) if run_present else None
        logger.info(f"{run_datetime_iso=} {profile=} top_dir={str(top_dir)!r} directory={str(directory)!r} {overwrite=} {meta_diff=}")
        if not run_present or not profile:
            logger.warning(f"SKIP {run_datetime_iso!r} - no corresponding profile found")
            return
        self._at_beginning(profile)
        msgs = []
        if directory and (ex := try_to_iterate_dir(directory)):
            msgs.append(f"SKIP {run_datetime_iso!r} - cannot access target directory - {ex}")
        if top_dir:
            if not top_dir.is_absolute():
                top_dir = self.s.source_dir / top_dir
            relative_top_dir = derive_relative_p(top_dir, self.s.source_dir)  # includes validation
        else:
            relative_top_dir = None  # no filtering
        if msgs:
            logger.warning('; '.join(msgs))
            return
        # iter files in top_dir for the run and extract each one
        for bak_path, src_path in self._rdb.iter_bak_src_paths(run_datetime_iso, relative_top_dir):
            backup_path = self.s.backup_base_dir_for_profile / bak_path
            original_source_path = self.s.source_dir / src_path
            if directory:  # different target dir requested
                relative_target_file = derive_relative_p(original_source_path, self.s.backup_base_dir_for_profile)  # includes validation
                target_path = directory / relative_target_file
            else:
                target_path = original_source_path
            self.extract_archive(backup_path, target_path, overwrite, meta_diff)
        self._at_end()

    def extract_for_profile2(self, profile: str, top_archive_dir: Path | None, directory: Path | None, overwrite: bool, meta_diff: bool):
        """Extract the lastest version of each file found in backup hierarchy for profile
        """
        self._at_beginning(profile)
        if directory is None:
            directory = self._profile_to_settings[profile].source_dir
        msgs = []
        if ex := try_to_iterate_dir(directory):
            msgs.append(f"SKIP {profile!r} - cannot access target directory - {ex}")
        if top_archive_dir:
            if not top_archive_dir.is_absolute():
                top_archive_dir = self.s.backup_base_dir_for_profile / top_archive_dir
            if ex := try_to_iterate_dir(top_archive_dir):
                msgs.append(f"SKIP {profile!r} - archive-dir doesn't exist - {ex}")
            elif not top_archive_dir.as_posix().startswith(self.s.backup_base_dir_for_profile.as_posix()):
                msgs.append(f"SKIP {profile!r} - archive-dir is not under backup_base_dir_for_profile: "
                            f"top_archive_dir={str(top_archive_dir)!r} backup_base_dir_for_profile={str(self.s.backup_base_dir_for_profile)!r}")
        logger.info(f"{profile=} top_archive_dir={str(top_archive_dir) if top_archive_dir else None!r} directory={str(directory)!r} {overwrite=} {meta_diff=}")
        if msgs:
            logger.warning('; '.join(msgs))
            return
        if not self._confirm_extraction_into_directory(directory, top_archive_dir, self.s.backup_base_dir_for_profile):
            return
        if top_archive_dir:
            should_attempt_recursive = False
            for dirpath, dirnames, filenames in os.walk(top_archive_dir):
                if archive_file := find_last_file_in_basedir(top_archive_dir, filenames, RX_ARCHIVE_SUFFIX, nonzero=True):
                    self.extract_latest_file(self.s.backup_base_dir_for_profile, top_archive_dir, directory, overwrite, meta_diff, filenames, archive_file)
                else:
                    should_attempt_recursive = True
                break
            if should_attempt_recursive:
                for dirpath, dirnames, filenames in os.walk(top_archive_dir):
                    self.extract_latest_file(self.s.backup_base_dir_for_profile, Path(dirpath), directory, overwrite, meta_diff, filenames)
        else:
            for basedir, dirnames, filenames in os.walk(self.s.backup_base_dir_for_profile):
                if filenames:
                    top_archive_dir = Path(basedir)  # the original file, in the mirrored directory tree
                    self.extract_latest_file(self.s.backup_base_dir_for_profile, top_archive_dir, directory, overwrite, meta_diff, filenames)
        self._at_end()

    def extract_for_profile(self, profile: str, top_archive_dir: Path | None, directory: Path | None, overwrite: bool, meta_diff: bool):
        """Extract the lastest version of each file recorded in the DB for profile
        """
        self._at_beginning(profile)
        _directory = directory or self.s.source_dir
        msgs = []
        if ex := try_to_iterate_dir(_directory):
            msgs.append(f"SKIP {profile!r} - cannot access target directory - {ex}")
        if top_archive_dir:
            if not top_archive_dir.is_absolute():
                top_archive_dir = self.s.backup_base_dir_for_profile / top_archive_dir
            if ex := try_to_iterate_dir(top_archive_dir):
                msgs.append(f"SKIP {profile!r} - archive-dir doesn't exist - {ex}")
            elif not top_archive_dir.as_posix().startswith(self.s.backup_base_dir_for_profile.as_posix()):
                msgs.append(f"SKIP {profile!r} - archive-dir is not under backup_base_dir_for_profile: "
                            f"top_archive_dir={str(top_archive_dir)!r} backup_base_dir_for_profile={str(self.s.backup_base_dir_for_profile)!r}")
        logger.info(f"{profile=} top_archive_dir={str(top_archive_dir) if top_archive_dir else None!r} directory={str(_directory)!r} {overwrite=} {meta_diff=}")
        if msgs:
            logger.warning('; '.join(msgs))
            return
        if not self._confirm_extraction_into_directory(_directory, top_archive_dir, self.s.backup_base_dir_for_profile):
            return
        for archive_file, target_file in self._rdb.iter_latest_archives_and_targets(top_archive_dir, directory):
            self.extract_archive(archive_file, target_file, overwrite, meta_diff)
        self._at_end()

    @staticmethod
    def _confirm_extraction_into_directory(directory: Path, top_archive_dir: Path, backup_base_dir_for_profile: Path):
        if top_archive_dir:
            relative_top_archive_dir = derive_relative_p(top_archive_dir, backup_base_dir_for_profile)
            target_dir = directory / relative_top_archive_dir
            target = str(target_dir)
        else:
            target = str(directory)
        answer = input(f"\n   Begin extraction into {target}?  [N/y] ")
        logger.info(f":  {answer=}  {target}")
        return answer in ['y', 'Y']

    def extract_latest_file(self, backup_base_dir_for_profile, archive_dir: Path, directory: Path, overwrite: bool, meta_diff: bool,
                            filenames: list[str] | None = None, archive_file: Path | None = None):
        if archive_file is None:
            archive_file = find_last_file_in_basedir(archive_dir, filenames, RX_ARCHIVE_SUFFIX)
        if archive_file:
            relative_file_parent = derive_relative_p(archive_dir.parent, backup_base_dir_for_profile)
            target_file = directory / relative_file_parent / archive_dir.name
            self.extract_archive(archive_file, target_file, overwrite, meta_diff)
        else:
            # logger.warning(f"no archive found in {str(archive_dir)}")
            pass

    def extract_archive(self, archive_file: Path, target_file: Path, overwrite: bool, meta_diff: bool):
        try:
            st_stat = target_file.stat()
            target_file_exists = True
        except OSError:
            st_stat = None
            target_file_exists = False
        if target_file_exists:
            if meta_diff and self.derive_mtime_size(archive_file) == (self.calc_mtime_str(datetime.fromtimestamp(st_stat.st_mtime)), st_stat.st_size):
                should_extract = False
                logger.info(f"skipping {derive_relative_p(archive_file.parent, self.s.backup_base_dir_for_profile)} - mtime and size are the same as in the target file")
            elif overwrite or self._ask_to_overwrite(target_file):
                should_extract = True
            else:
                should_extract = False
                warning = f"skipping {target_file} - file exists"
                self._warnings.append(warning)
                logger.warning(warning)
        else:
            should_extract = True
        if should_extract:
            self._extract(archive_file, target_file)

    @staticmethod
    def _ask_to_overwrite(target_file):
        answer = input(f"\n{target_file}\n The above file exists. Overwrite it? [N/y] ")
        logger.info(f":  {answer=}  {target_file}")
        return answer in ['y', 'Y']

    def _extract(self, archive_file: Path, target_file: Path):
        if archive_file.suffix == self.DOT_ZIPX:
            self._extract_zipx(archive_file, target_file)
        else:
            self._extract_tar(archive_file, target_file)

    def _extract_zipx(self, archive_file: Path, target_file: Path):
        logger.info(f":@ {archive_file.parent.name} | {archive_file.name} -> {target_file}")
        with pyzipper.AESZipFile(archive_file) as zf:
            zf.setpassword(self.s.password)
            member = cast(zipfile.ZipInfo, zf.infolist()[0])
            if member.filename == target_file.name:
                zf.extract(member, target_file.parent)
                mtime_str, _ = self.derive_mtime_size(archive_file)
                self.set_mtime(target_file, self.calc_mtime_dt(mtime_str))
            else:
                error = f"archived-file name is different than the archive-container-directory name: {member.filename} != {target_file.name}"
                self._errors.append(error)
                logger.error(error)

    def _extract_tar(self, archive_file: Path, target_file: Path):
        logger.info(f":@ {archive_file.parent.name} | {archive_file.name} -> {target_file}")
        with tarfile.open(archive_file) as tf:
            member = cast(tarfile.TarInfo, tf.getmembers()[0])
            if member.name == target_file.name:
                if (vi.major, vi.minor) >= (3, 12):
                    tf.extract(member, target_file.parent, filter='tar')
                else:
                    tf.extract(member, target_file.parent)
            else:
                error = f"archived-file name is different than the archive-container-directory name: {member.name} != {target_file.name}"
                self._errors.append(error)
                logger.error(error)


def try_to_iterate_dir(path: Path):
    try:
        for _ in path.iterdir():
            break
    except OSError as e:
        return e
    return None


def compute_blake2b_checksum(f: BufferedIOBase) -> str:
    # https://docs.python.org/3/library/functions.html#open
    # The type of file object returned by the open() function depends on the mode.
    # When used to open a file in a binary mode with buffering, the returned class is a subclass of io.BufferedIOBase.
    # When buffering is disabled, the raw stream, a subclass of io.RawIOBase, io.FileIO, is returned.
    # https://docs.python.org/3/library/io.html#io.BufferedIOBase
    # BufferedIOBase: [read(), readinto() and write(),] unlike their RawIOBase counterparts, [...] will never return None.
    # read(): An empty bytes object is returned if the stream is already at EOF.
    b = blake2b()
    for chunk in iter(lambda: f.read(32768), b''):
        b.update(chunk)
    return b.hexdigest()


def not_used(func):
    return NotImplemented


@not_used
def find_last_file_in_dir(archive_dir: Path, pattern: Pattern | None = None, nonzero=True) -> Path | None:
    try:
        for dir_entry in sorted(os.scandir(archive_dir), key=lambda x: x.name, reverse=True):
            if dir_entry.is_file() and (pattern is None or pattern.search(dir_entry.name)) and (not nonzero or dir_entry.stat().st_size > 0):
                return Path(dir_entry)
    except FileNotFoundError as ex:
        # logger.warning(ex)
        pass
    return None


def find_last_file_in_basedir(basedir: str | Path, filenames: list[str] | None = None, pattern: Pattern | None = None, nonzero=True) -> Path | None:
    """As in: `for basedir, dirnames, filenames in os.walk(top_dir):`
    :return: Path of `filename` matching `pattern`, and of size > 0 if nonzero
    """
    if filenames is None:
        filenames = [de.name for de in os.scandir(basedir) if de.is_file()]
    for file in sorted(filenames, reverse=True):
        if pattern is None or pattern.search(file):
            path = Path(basedir, file)
            if not nonzero or path.stat().st_size > 0:
                return path
    return None


class RumarDB:
    """
    all dirs/paths in the DB are represented as_posix()
    xxx_dir := the base directory
    xxx_path := the remaining path, relative to the base directory
    xxx_name := the name, like Path.name
    """
    SPACE = ' '
    ddl = {
        'table': {
            'source_dir': dedent('''\
            CREATE TABLE IF NOT EXISTS source_dir (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_dir TEXT UNIQUE NOT NULL
            ) STRICT;'''),
            'source': dedent('''\
            CREATE TABLE IF NOT EXISTS source (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_dir_id INTEGER NOT NULL REFERENCES source_dir (id),
                src_path TEXT NOT NULL,
                CONSTRAINT u_source_src_dir_id_src_path UNIQUE (src_dir_id, src_path)
            ) STRICT;'''),
            'profile': dedent('''\
            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile TEXT UNIQUE NOT NULL
            ) STRICT;'''),
            'run': dedent('''\
            CREATE TABLE IF NOT EXISTS run (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_datetime_iso TEXT UNIQUE NOT NULL,
                profile_id INTEGER NOT NULL REFERENCES profile (id)
            ) STRICT;'''),
            'backup_base_dir_for_profile': dedent('''\
            CREATE TABLE IF NOT EXISTS backup_base_dir_for_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bak_dir TEXT UNIQUE NOT NULL
            ) STRICT;'''),
            'backup': dedent('''\
            CREATE TABLE IF NOT EXISTS backup (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES run (id),
                reason TEXT NOT NULL,
                bak_dir_id INTEGER NOT NULL REFERENCES backup_base_dir_for_profile (id),
                src_id INTEGER NOT NULL REFERENCES source (id),
                bak_name TEXT,
                blake2b TEXT,
                CONSTRAINT u_bak_dir_id_src_id_bak_name UNIQUE (bak_dir_id, src_id, bak_name)
            ) STRICT;'''),
            'unchanged': dedent('''\
            CREATE TABLE IF NOT EXISTS unchanged (
                run_id INTEGER NOT NULL REFERENCES run (id),
                src_id INTEGER NOT NULL REFERENCES source (id),
                CONSTRAINT pk_unchanged_source PRIMARY KEY (run_id, src_id)
            ) STRICT;'''),
        },
        'indexes': dedent('''\
        --CREATE INDEX IF NOT EXISTS i_backup_blake2b ON backup (blake2b);
        CREATE INDEX IF NOT EXISTS i_backup_reason ON backup (reason);'''),
        'view': {
            'v_backup': dedent('''\
            CREATE VIEW IF NOT EXISTS v_backup AS
            SELECT b.id, run_id, run_datetime_iso, profile, reason, bak_dir, src_path, bak_name, substr(blake2b, 1, 10) _blake2b
            FROM backup b
            JOIN backup_base_dir_for_profile bd ON bak_dir_id = bd.id
            JOIN "source" ON src_id = "source".id
            JOIN run ON run_id = run.id
            JOIN profile ON run.profile_id = profile.id;'''),
            'v_run': dedent('''\
            CREATE VIEW IF NOT EXISTS v_run AS
            SELECT run.id run_id, profile_id, run_datetime_iso, profile
            FROM run
            JOIN profile ON profile_id = profile.id;'''),
        },
    }
    _profile_to_id = {}
    _run_to_id = {}
    _src_dir_to_id = {}
    _source_to_id = {}
    _bak_dir_to_id = {}
    _backup_to_checksum = {}

    def __init__(self, profile: str, s: Settings):
        self._profile = profile
        self.s = s
        db = sqlite3.connect(s.db_path)
        db.execute('PRAGMA foreign_keys = ON')
        self._migrate_backup_to_bak_name_if_required(db)
        self._create_tables_and_indexes_if_not_exist(db)
        self._recreate_views(db)
        self._delete_from_unchanged(db, run_id_offset=10)
        self._db = db
        self._cur = db.cursor()
        if not self._profile_to_id:
            self._load_data_into_memory()
        # make sure run_datetime_iso is unique
        while (run_datetime_iso := self.make_run_datetime_iso()) in self._run_to_id:
            sleep(0.25)
        self._run_datetime_iso = run_datetime_iso
        self._profile_id = None
        self._run_id = None
        self._src_dir_id = None
        self._bak_dir_id = None
        self._init_ids()
        if self._profile not in self._profile_to_id:
            self._save_initial_state()
        self._unchanged_paths = {}

    @classmethod
    def make_run_datetime_iso(cls):
        return datetime.now().astimezone().isoformat(sep=cls.SPACE, timespec='seconds')

    @classmethod
    def _create_tables_and_indexes_if_not_exist(cls, db):
        cur = db.cursor()
        for stmt in cls.ddl['table'].values():
            cur.execute(stmt)
        cur.executescript(cls.ddl['indexes'])
        cur.close()

    @classmethod
    def _recreate_views(cls, db):
        cur = db.cursor()
        for name, stmt in cls.ddl['view'].items():
            cur.execute('DROP VIEW IF EXISTS ' + name)
            cur.execute(stmt)
        cur.close()

    @classmethod
    def _migrate_backup_to_bak_name_if_required(cls, db):
        for _ in db.execute("SELECT 1 FROM pragma_table_info('backup') WHERE name = 'bak_path'"):
            cls._migrate_to_bak_name(db)

    @classmethod
    def _migrate_to_bak_name(cls, db):
        cur = db.cursor()
        cur.execute('DROP VIEW IF EXISTS v_backup')
        cur.execute('DROP VIEW IF EXISTS v_run')
        cur.execute('DROP INDEX IF EXISTS i_backup_mtime_iso')
        cur.execute('DROP INDEX IF EXISTS i_backup_size')
        bak_name_missing = True
        for _ in cur.execute("SELECT 1 FROM pragma_table_info('backup') WHERE name = 'bak_name'"):
            bak_name_missing = False
        if bak_name_missing:
            cur.execute('ALTER TABLE backup ADD bak_name TEXT')
            for row in db.execute('SELECT id, bak_path FROM backup'):
                lst = row[1].rsplit('/', 1)
                bak_name = lst[1] if len(lst) == 2 else lst[0]
                cur.execute('UPDATE backup SET bak_name = ? WHERE id = ?', (bak_name, row[0]))
            db.commit()
        cur.execute('ALTER TABLE backup RENAME TO backup_old')
        cur.execute(cls.ddl['table']['backup'])
        cur.execute(dedent('''\
        INSERT INTO backup (id, run_id, reason, bak_dir_id, src_id, bak_name, blake2b)
        SELECT id, run_id, reason, bak_dir_id, src_id, bak_name, blake2b
        FROM backup_old
        ORDER BY id'''))
        cur.execute('DROP TABLE backup_old')
        cur.close()
        db.commit()
        # db.execute('VACUUM')

    @staticmethod
    def _delete_from_unchanged(db, run_id_offset=10):
        stmt = dedent('''\
            DELETE FROM unchanged
            WHERE run_id < (
                SELECT DISTINCT run_id
                FROM unchanged
                ORDER BY run_id DESC
                LIMIT 1 OFFSET ?
            )
        ''')
        db.execute(stmt, (run_id_offset,))
        db.commit()
        db.execute('VACUUM')

    def _load_data_into_memory(self):
        for profile, id_ in execute(self._cur, 'SELECT profile, id FROM profile'):
            self._profile_to_id[profile] = id_
        for run_datetime_iso, id_ in execute(self._cur, 'SELECT run_datetime_iso, id FROM run'):
            self._run_to_id[run_datetime_iso] = id_
        for src_dir, id_ in execute(self._cur, 'SELECT src_dir, id FROM source_dir'):
            self._src_dir_to_id[src_dir] = id_
        for src_dir_id, src_path, id_ in execute(self._cur, 'SELECT src_dir_id, src_path, id FROM source'):
            self._source_to_id[(src_dir_id, src_path)] = id_
        for bak_dir, id_ in execute(self._cur, 'SELECT bak_dir, id FROM backup_base_dir_for_profile'):
            self._bak_dir_to_id[bak_dir] = id_
        for bak_dir_id, src_id, bak_name, blake2b_checksum in execute(self._cur, 'SELECT bak_dir_id, src_id, bak_name, blake2b FROM backup'):
            self._backup_to_checksum[(bak_dir_id, src_id, bak_name)] = blake2b_checksum

    def _print_dicts(self):
        print(str(self.s.db_path))
        print(self._profile_to_id)
        print(self._run_to_id)
        print(self._src_dir_to_id)
        print(self._source_to_id)
        print(self._bak_dir_to_id)
        print(self._backup_to_checksum)

    def _init_ids(self):
        # profile
        profile = self._profile
        if not (profile_id := self._profile_to_id.get(profile)):
            execute(self._cur, 'INSERT INTO profile (profile) VALUES (?)', (profile,))
            profile_id = execute(self._cur, 'SELECT id FROM profile WHERE profile = ?', (profile,)).fetchone()[0]
            self._profile_to_id[profile] = profile_id
        self._profile_id = profile_id
        # run
        run_datetime_iso = self._run_datetime_iso
        if not (run_id := self._run_to_id.get((profile_id, run_datetime_iso))):
            execute(self._cur, 'INSERT INTO run (profile_id, run_datetime_iso) VALUES (?,?)', (profile_id, run_datetime_iso))
            run_id = execute(self._cur, 'SELECT id FROM run WHERE profile_id = ? AND run_datetime_iso = ?', (profile_id, run_datetime_iso)).fetchone()[0]
            self._run_to_id[(profile_id, run_datetime_iso)] = run_id
        self._run_id = run_id
        # source_dir
        src_dir = self.s.source_dir.as_posix()
        if not (src_dir_id := self._src_dir_to_id.get(src_dir)):
            execute(self._cur, 'INSERT INTO source_dir (src_dir) VALUES (?)', (src_dir,))
            src_dir_id = execute(self._cur, 'SELECT id FROM source_dir WHERE src_dir = ?', (src_dir,)).fetchone()[0]
            self._src_dir_to_id[src_dir] = src_dir_id
        self._src_dir_id = src_dir_id
        # backup_base_dir_for_profile
        bak_dir = self.s.backup_base_dir_for_profile.as_posix()
        if not (bak_dir_id := self._bak_dir_to_id.get(bak_dir)):
            execute(self._cur, 'INSERT INTO backup_base_dir_for_profile (bak_dir) VALUES (?)', (bak_dir,))
            bak_dir_id = execute(self._cur, 'SELECT id FROM backup_base_dir_for_profile WHERE bak_dir = ?', (bak_dir,)).fetchone()[0]
            self._bak_dir_to_id[bak_dir] = bak_dir_id
        self._bak_dir_id = bak_dir_id

    def _save_initial_state(self):
        """Walks `backup_base_dir_for_profile` and saves latest archive of each source, whether the source file currently exists or not"""
        for basedir, dirnames, filenames in os.walk(self.s.backup_base_dir_for_profile):
            if latest_archive := find_last_file_in_basedir(basedir, filenames, RX_ARCHIVE_SUFFIX):
                relative_archive_dir = derive_relative_p(latest_archive.parent, self.s.backup_base_dir_for_profile)
                file_path = self.s.source_dir / relative_archive_dir
                relative_p = derive_relative_p(file_path, self.s.source_dir)
                checksum_file = Rumar.compose_checksum_file_path(latest_archive)
                try:
                    blake2b_checksum = checksum_file.read_text(UTF8)
                except FileNotFoundError:
                    # blake2b_checksum = Rumar.compute_checksum_of_file_in_archive(latest_archive, self.s.password)
                    blake2b_checksum = None
                create_reason = CreateReason.INIT
                sign = create_reason.value
                reason = create_reason.name
                logger.info(f"{sign} {relative_p}  {latest_archive.name}  {reason} {latest_archive.parent}")
                self.save(create_reason, relative_p, latest_archive, blake2b_checksum)

    def save(self, create_reason: CreateReason, relative_p: str, archive_path: Path | None, blake2b_checksum: str | None):
        # logger.debug(f"{create_reason}, {relative_p}, {archive_path.name if archive_path else None}, {blake2b_checksum})")
        # source
        src_path = relative_p
        src_dir_id = self._src_dir_id
        if not (src_id := self._source_to_id.get((src_dir_id, src_path))):
            execute(self._cur, 'INSERT INTO source (src_dir_id, src_path) VALUES (?, ?)', (src_dir_id, src_path))
            src_id = execute(self._cur, 'SELECT id FROM source WHERE src_dir_id = ? AND src_path = ?', (src_dir_id, src_path)).fetchone()[0]
            self._source_to_id[(src_dir_id, src_path)] = src_id
        # backup
        run_id = self._run_id
        bak_dir_id = self._bak_dir_id
        reason = create_reason.name[0]
        bak_name = archive_path.name if archive_path else None
        execute(self._cur, 'INSERT INTO backup (run_id, reason, bak_dir_id, src_id, bak_name, blake2b) VALUES (?, ?, ?, ?, ?, ?)',
                (run_id, reason, bak_dir_id, src_id, bak_name, blake2b_checksum))
        self._backup_to_checksum[(bak_dir_id, src_id, bak_name)] = blake2b_checksum
        self._db.commit()

    def save_unchanged(self, relative_p: str):
        src_path = relative_p
        stmt = 'INSERT INTO unchanged (run_id, src_id) SELECT ?, id FROM source WHERE src_dir_id = ? AND src_path = ?'
        params = (self._run_id, self._src_dir_id, src_path)
        execute(self._cur, stmt, params)
        self._db.commit()

    def identify_and_save_deleted(self):
        """
        Inserts a DELETE record for each path in the DB that's no longer available in source_dir files.
        Selects from backup latest src_paths for profile minus already deleted ones, minus src_paths seen in this run,
        i.e. both changed and unchanged files. The result is a list of newly deleted src_paths.
        """
        query = dedent('''\
        INSERT INTO backup (run_id, reason, bak_dir_id, src_id)
        SELECT ?, ?, bak_dir_id, src_id
        FROM backup b
        JOIN ( -- latest src files for profile, minus already deleted ones
            SELECT max(backup.id) id
            FROM backup
            JOIN run ON run.id = backup.run_id AND run.profile_id = ?
            GROUP BY src_id
        ) x ON b.id = x.id AND b.reason != ?
        WHERE b.run_id != ? -- minus file changed in this run
        AND NOT EXISTS ( -- minus files not changed in this run
            SELECT 1
            FROM unchanged u
            WHERE b.src_id = u.src_id AND u.run_id = ?
        );''')
        run_id = self._run_id
        reason_d = CreateReason.DELETE.name[0]
        profile_id = self._profile_id
        execute(self._cur, query, (run_id, reason_d, profile_id, reason_d, run_id, run_id))
        self._db.commit()

    def close_db(self):
        self._cur.close()
        self._db.close()

    def get_latest_archive_for_source(self, relative_p: str) -> Path | None:
        stmt = dedent('''\
            SELECT bak_dir, bak_name
            FROM backup b 
            JOIN run r ON r.id = b.run_id AND r.profile_id = ? 
            JOIN backup_base_dir_for_profile bd ON b.bak_dir_id = bd.id 
            JOIN "source" s ON b.src_id = s.id AND s.src_path = ?
            JOIN source_dir sd ON s.src_dir_id = sd.id AND sd.src_dir = ?
            ORDER BY b.id DESC
            LIMIT 1
        ''')
        params = (self._profile_id, relative_p, self.s.source_dir.as_posix())
        result = None
        for row in execute(self._cur, stmt, params):
            bak_dir, bak_name = row
            if bak_name:
                result = Path(bak_dir, relative_p, bak_name)
        logger.debug(f"=> {result}")
        return result

    def get_blake2b_checksum(self, archive_path: Path) -> str | None:
        bak_dir = self.s.backup_base_dir_for_profile.as_posix()
        if bak_dir_id := self._bak_dir_to_id.get(bak_dir):
            src_dir = self.s.source_dir.as_posix()
            src_dir_id = self._src_dir_to_id.get(src_dir)
            src_path = derive_relative_p(archive_path.parent, self.s.backup_base_dir_for_profile)
            src_id = self._source_to_id[(src_dir_id, src_path)]
            bak_name = archive_path.name
            return self._backup_to_checksum.get((bak_dir_id, src_id, bak_name))
        return None

    def set_blake2b_checksum(self, archive_path: Path, blake2b_checksum: str):
        bak_dir = self.s.backup_base_dir_for_profile.as_posix()
        bak_dir_id = self._bak_dir_to_id[bak_dir]
        src_dir = self.s.source_dir.as_posix()
        src_dir_id = self._src_dir_to_id.get(src_dir)
        src_path = derive_relative_p(archive_path.parent, self.s.backup_base_dir_for_profile)
        src_id = self._source_to_id[(src_dir_id, src_path)]
        bak_name = archive_path.name
        key = (bak_dir_id, src_id, bak_name)
        old_blake2b_checksum = self._backup_to_checksum[key]
        if old_blake2b_checksum and old_blake2b_checksum != blake2b_checksum:
            raise ValueError(f"({bak_dir}, {src_path}, {bak_name}) already in backup with a different blake2b_checksum: {old_blake2b_checksum}")
        self._db.execute('UPDATE backup SET blake2b = ? WHERE bak_dir_id = ? AND src_id = ? AND bak_name = ?', (blake2b_checksum, bak_dir_id, src_id, bak_name))
        self._db.commit()
        self._backup_to_checksum[key] = blake2b_checksum

    def close(self):
        self._db.close()

    def is_run_present(self, run_datetime_iso):
        return run_datetime_iso in self._run_to_id

    def get_run_datetime_isos(self, profile: str = None):
        where = f"WHERE profile = '{profile}'" if profile else ''
        query = dedent(f"""\
        SELECT run_datetime_iso, profile
        FROM run
        JOIN profile ON profile_id = profile.id
        {where}
        ORDER BY 1""")
        return self._db.execute(query).fetchall()

    def iter_path_for_run(self, top_archive_dir):
        query = dedent(f"""\
        SELECT 
        """)

    def iter_bak_src_paths(self, run_datetime_iso: str, relative_top_dir: str = None):
        if relative_top_dir:
            and_src_path_like = 'AND s.src_path LIKE ?'
            params = (run_datetime_iso, f"{relative_top_dir}/%")
        else:
            and_src_path_like = ''
            params = (run_datetime_iso,)
        query = dedent(f"""\
        SELECT s.src_path
        FROM backup b
        JOIN run r ON b.run_id = r.id
        JOIN source s ON b.src_id = s.id
        WHERE r.run_datetime_iso = ?
        {and_src_path_like}
        """)
        for row in self._db.execute(query, params):
            yield row[0]

    def iter_latest_archives_and_targets(self, top_archive_dir: Path = None, directory: Path = None):
        query = dedent('''\
        SELECT bd.bak_dir, s.src_path, b.bak_name, sd.src_dir
        FROM backup b
        JOIN backup_base_dir_for_profile bd ON b.bak_dir_id = bd.id 
        JOIN "source" s ON b.src_id = s.id
        JOIN source_dir sd ON s.src_dir_id = sd.id
        JOIN (
            SELECT max(b.id) id
            FROM backup b
            JOIN run r ON b.run_id = r.id AND r.profile_id = ?
            GROUP BY b.src_id
        ) x ON b.id = x.id
        WHERE b.reason != ?
        ''')
        top_archive_dir_psx = top_archive_dir.as_posix() if top_archive_dir else 'None'
        for row in execute(self._cur, query, (self._profile_id, CreateReason.DELETE.name[0])):
            bak_dir, src_path, bak_name, src_dir = row
            if top_archive_dir and not f"{bak_dir}/{src_path}".startswith(top_archive_dir_psx):
                continue
            _directory = directory or Path(src_dir)
            yield Path(bak_dir, src_path, bak_name), _directory / src_path


def execute(cur: sqlite3.Cursor | sqlite3.Connection, stmt: str, params: tuple | None = None, log=logger.debug):
    if params:
        sql_stmt = stmt.replace('?', '%r') % params
    else:
        sql_stmt = stmt
    log(sql_stmt)
    if params:
        result = cur.execute(stmt, params)
    else:
        result = cur.execute(stmt)
    if stmt.startswith('INSERT') or stmt.startswith('UPDATE') or stmt.startswith('DELETE'):
        log(f"{cur.rowcount=}")
    return result


class Broom:
    DASH = '-'
    DOT = '.'

    def __init__(self, profile_to_settings: ProfileToSettings):
        self._profile_to_settings = profile_to_settings
        self._db = BroomDB()
        self._path_to_lstat = {}

    @classmethod
    def is_archive(cls, name: str, archive_format: str) -> bool:
        return (name.endswith(cls.DOT + archive_format) or
                name.endswith(cls.DOT + RumarFormat.TAR.value))

    @staticmethod
    def is_checksum(name: str) -> bool:
        return name.endswith(Rumar.CHECKSUM_SUFFIX)

    @classmethod
    def derive_date(cls, name: str) -> date:
        iso_date_string = name[:10]
        y, m, d = iso_date_string.split(cls.DASH)
        return date(int(y), int(m), int(d))

    def sweep_all_profiles(self, *, is_dry_run: bool):
        for profile in self._profile_to_settings:
            self.sweep_profile(profile, is_dry_run=is_dry_run)

    def sweep_profile(self, profile, *, is_dry_run: bool):
        logger.info(profile)
        s = self._profile_to_settings[profile]
        if ex := try_to_iterate_dir(s.backup_base_dir_for_profile):
            logger.warning(f"SKIP {profile} - {ex}")
            return
        self.gather_info(s)
        self.delete_files(is_dry_run)

    def gather_info(self, s: Settings):
        archive_format = RumarFormat(s.archive_format).value
        date_older_than_x_days = date.today() - timedelta(days=s.min_age_in_days_of_backups_to_sweep)
        # the make-iterator logic is not extracted to a function so that logger prints the calling function's name
        if Command.SWEEP in s.commands_which_use_filters:
            iterator = iter_matching_files(Rath(s.backup_base_dir_for_profile, lstat_cache=self._path_to_lstat), s)
            logger.debug(f"{s.commands_which_use_filters=} => iter_matching_files")
        else:
            iterator = iter_all_files(Rath(s.backup_base_dir_for_profile, lstat_cache=self._path_to_lstat))
            logger.debug(f"{s.commands_which_use_filters=} => iter_all_files")
        old_enough_file_to_mdate = {}
        for rath in iterator:
            if self.is_archive(rath.name, archive_format):
                mdate = self.derive_date(rath.name)
                if mdate <= date_older_than_x_days:
                    old_enough_file_to_mdate[rath] = mdate
            elif not self.is_checksum(rath.name):
                logger.warning(f":! {str(rath)}  is unexpected (not an archive)")
        for rath in sorted_files_by_stem_then_suffix_ignoring_case(old_enough_file_to_mdate):
            self._db.insert(rath, mdate=old_enough_file_to_mdate[rath])
        self._db.commit()
        self._db.update_counts(s)

    def delete_files(self, is_dry_run):
        logger.log(METHOD_17, f"{is_dry_run=}")
        rm_action_info = 'would be removed' if is_dry_run else '-- removing'
        for dirname, basename, d, w, m, d_rm, w_rm, m_rm in self._db.iter_marked_for_removal():
            path = Path(dirname, basename)
            logger.info(f"-- {path.as_posix()}  {rm_action_info} because it's #{m_rm} in month {m}, #{w_rm} in week {w}, #{d_rm} in day {d}")
            if not is_dry_run:
                path.unlink()


class BroomDB:
    DATABASE = me.with_suffix('.sqlite') if logger.level <= logging.DEBUG else ':memory:'
    TABLE_PREFIX = 'broom'
    TABLE_DT_FRMT = '_%Y%m%d_%H%M%S'
    DATE_FORMAT = '%Y-%m-%d'
    WEEK_FORMAT = '%Y-%W'  # Monday as the first day of the week, zero-padded
    WEEK_ONLY_FORMAT = '%W'
    MONTH_FORMAT = '%Y-%m'
    DUNDER = '__'

    def __init__(self):
        self._db = sqlite3.connect(self.DATABASE)
        self._table = f"{self.TABLE_PREFIX}{datetime.now().strftime(self.TABLE_DT_FRMT)}"
        logger.debug(f"{self.DATABASE} | {self._table}")
        self._create_table_if_not_exists()

    @classmethod
    def calc_week(cls, mdate: date) -> str:
        """
        consider week 0 as previous year's last week
        """
        m = mdate.month
        d = mdate.day
        if m == 1 and d < 7 and mdate.strftime(cls.WEEK_ONLY_FORMAT) == '00':
            mdate = mdate.replace(day=1) - timedelta(days=1)
        return mdate.strftime(cls.WEEK_FORMAT)

    def _create_table_if_not_exists(self):
        ddl = dedent(f"""\
            CREATE TABLE IF NOT EXISTS {self._table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dirname TEXT NOT NULL,
                basename TEXT NOT NULL,
                d TEXT NOT NULL,
                w TEXT NOT NULL,
                m TEXT NOT NULL,
                d_rm TEXT,
                w_rm TEXT,
                m_rm TEXT
            )
            """)
        self._db.execute(ddl)

    def _create_indexes_if_not_exist(self):
        index_ddls = (f"CREATE INDEX IF NOT EXISTS idx_dirname_d ON {self._table} (dirname, d)",
                      f"CREATE INDEX IF NOT EXISTS idx_dirname_w ON {self._table} (dirname, w)",
                      f"CREATE INDEX IF NOT EXISTS idx_dirname_m ON {self._table} (dirname, m)")
        for ddl in index_ddls:
            self._db.execute(ddl)

    def insert(self, path: Path, mdate: date, should_commit=False):
        # logger.log(METHOD_17, f"{path.as_posix()}")
        params = (
            path.parent.as_posix(),
            path.name,
            mdate.strftime(self.DATE_FORMAT),
            self.calc_week(mdate),
            mdate.strftime(self.MONTH_FORMAT),
        )
        ins_stmt = f"INSERT INTO {self._table} (dirname, basename, d, w, m) VALUES (?,?,?,?,?)"
        self._db.execute(ins_stmt, params)
        if should_commit:
            self._db.commit()

    def commit(self):
        self._db.commit()

    def update_counts(self, s: Settings):
        self._create_indexes_if_not_exist()
        self._update_d_rm(s)
        self._update_w_rm(s)
        self._update_m_rm(s)

    def _update_d_rm(self, s: Settings):
        """Sets d_rm, putting the information about 
        backup-file number in a day to be removed,
        maximal backup-file number in a day to be removed,
        count of backups pef files in a day,
        backups to keep per file in a day.
        To find the files, the SQL query looks for 
        months with the files count bigger than monthly backups to keep,
        weeks with the files count bigger than weekly backups to keep,
        days with the files count bigger than daily backups to keep.
        """
        stmt = dedent(f"""\
        SELECT * FROM (
            SELECT br.dirname, br.d, br.id, dd.cnt, row_number() OVER win1 AS num
            FROM {self._table} br
            JOIN (
                SELECT dirname, m, count(*) cnt
                FROM {self._table} 
                GROUP BY dirname, m
                HAVING count(*) > {s.number_of_backups_per_month_to_keep}
            ) mm ON br.dirname = mm.dirname AND br.m = mm.m
            JOIN (
                SELECT dirname, w, count(*) cnt
                FROM {self._table} 
                GROUP BY dirname, w
                HAVING count(*) > {s.number_of_backups_per_week_to_keep}
            ) ww ON br.dirname = ww.dirname AND br.w = ww.w
            JOIN (
                SELECT dirname, d, count(*) cnt
                FROM {self._table} 
                GROUP BY dirname, d
                HAVING count(*) > {s.number_of_backups_per_day_to_keep}
            ) dd ON br.dirname = dd.dirname AND br.d = dd.d
            WINDOW win1 AS (PARTITION BY br.dirname, br.d ORDER BY br.dirname, br.d, br.id)
        )
        WHERE num <= cnt - {s.number_of_backups_per_day_to_keep}
        ORDER BY dirname, d, id
        """)
        db = self._db
        rows = db.execute(stmt).fetchall()
        cur = db.cursor()
        for row in rows:
            dirname, d, broom_id, cnt, num = row
            max_num = max(row[4] for row in rows if row[0] == dirname and row[1] == d)
            updt_stmt = dedent(f"""\
                UPDATE {self._table}
                SET d_rm = '{num} of {max_num} (max {cnt} - {s.number_of_backups_per_day_to_keep})'
                WHERE id = ?
                """)
            cur.execute(updt_stmt, (broom_id,))
        db.commit()

    def _update_w_rm(self, s: Settings):
        """Sets w_rm, putting the information about 
        backup-file number in a week to be removed,
        maximal backup-file number in a week to be removed,
        count of all backups per file in a week,
        backups to keep per file in a week.
        To find the files, the SQL query looks for
        days marked for removal, calculated based on
        months with the files count bigger than monthly backups to keep,
        weeks with the files count bigger than weekly backups to keep,
        days with the files count bigger than daily backups to keep.
        """
        stmt = dedent(f"""\
        SELECT * FROM (
            SELECT br.dirname, br.w, br.id, ww.cnt, row_number() OVER win1 AS num
            FROM {self._table} br
            JOIN (
                SELECT dirname, w, count(*) cnt
                FROM {self._table} 
                GROUP BY dirname, w
                HAVING count(*) > {s.number_of_backups_per_week_to_keep}
            ) ww ON br.dirname = ww.dirname AND br.w = ww.w
            WHERE br.d_rm IS NOT NULL
            WINDOW win1 AS (PARTITION BY br.dirname, br.w ORDER BY br.dirname, br.w, br.id)
        )
        WHERE num <= cnt - {s.number_of_backups_per_week_to_keep}
        ORDER BY dirname, w, id
        """)
        db = self._db
        rows = db.execute(stmt).fetchall()
        cur = db.cursor()
        for row in rows:
            dirname, w, broom_id, cnt, num = row
            max_num = max(row[4] for row in rows if row[0] == dirname and row[1] == w)
            updt_stmt = dedent(f"""\
                UPDATE {self._table}
                SET w_rm = '{num} of {max_num} (max {cnt} - {s.number_of_backups_per_week_to_keep})'
                WHERE id = ?
                """)
            cur.execute(updt_stmt, (broom_id,))
        db.commit()

    def _update_m_rm(self, s: Settings):
        """Sets m_rm, putting the information about 
        backup-file number in a month to be removed,
        maximal backup-file number in a month to be removed,
        count of all backups per file in a month,
        backups to keep per file in a month.
        To find the files, the SQL query looks for 
        weeks marked for removal, calculated based on
        months with the files count bigger than monthly backups to keep,
        weeks with the files count bigger than weekly backups to keep,
        days with the files count bigger than daily backups to keep.
        """
        stmt = dedent(f"""\
        SELECT * FROM (
            SELECT br.dirname, br.m, br.id, mm.cnt, row_number() OVER win1 AS num
            FROM {self._table} br
            JOIN (
                SELECT dirname, m, count(*) cnt
                FROM {self._table} 
                GROUP BY dirname, m
                HAVING count(*) > {s.number_of_backups_per_month_to_keep}
            ) mm ON br.dirname = mm.dirname AND br.m = mm.m
            WHERE br.w_rm IS NOT NULL
            WINDOW win1 AS (PARTITION BY br.dirname, br.m ORDER BY br.dirname, br.m, br.id)
        )
        WHERE num <= cnt - {s.number_of_backups_per_month_to_keep}
        ORDER BY dirname, m, id
        """)
        db = self._db
        rows = db.execute(stmt).fetchall()
        cur = db.cursor()
        for row in rows:
            dirname, m, broom_id, cnt, num = row
            max_num = max(row[4] for row in rows if row[0] == dirname and row[1] == m)
            updt_stmt = dedent(f"""\
                UPDATE {self._table}
                SET m_rm = '{num} of {max_num} (max {cnt} - {s.number_of_backups_per_month_to_keep})'
                WHERE id = ?
                """)
            cur.execute(updt_stmt, (broom_id,))
        db.commit()

    def iter_marked_for_removal(self) -> Generator[tuple[str, str, str, str, str, str, str, str], None, None]:
        stmt = dedent(f"""\
            SELECT dirname, basename, d, w, m, d_rm, w_rm, m_rm
            FROM {self._table}
            WHERE m_rm IS NOT NULL
            ORDER BY dirname, basename
            """)
        for row in self._db.execute(stmt):
            yield row


if __name__ == '__main__':
    main()
