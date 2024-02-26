#!/usr/bin/python3
# rumar – a file-backup utility
# Copyright (C) 2023, 2024  macmarrum
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
import stat
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from enum import Enum
from hashlib import blake2b
from pathlib import Path
from textwrap import dedent
from os import PathLike
from typing import Iterator, Union, Optional, Literal, Pattern, Any, Iterable, BinaryIO, cast

vi = sys.version_info
assert (vi.major, vi.minor) >= (3, 9), 'expected Python 3.9 or higher'

try:
    import pyzipper
except ImportError:
    print('pyzipper is missing => no support for zipx')

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


def log_record_factory(name, level, fn, lno, msg, args, exc_info, func=None, sinfo=None, **kwargs):
    """Add 'levelShort' field to LogRecord, to be used in 'format'"""
    log_record = logging.LogRecord(name, level, fn, lno, msg, args, exc_info, func, sinfo, **kwargs)
    log_record.levelShort = LEVEL_TO_SHORT.get(level, SHORT_DEFAULT)
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
format = "{levelShort} {asctime}: {funcName:24} {msg}"
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
    print(f":: loading logging config from {rumar_logging_toml_path}")
    dict_config = tomllib.load(rumar_logging_toml_path.open('rb'))
else:
    print(f":: loading default logging config")
    dict_config = tomllib.loads(LOGGING_TOML_DEFAULT)
logging.config.dictConfig(dict_config)
logger = logging.getLogger('rumar')

store_true = 'store_true'
PathAlike = Union[str, PathLike[str]]
UTF8 = 'UTF-8'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--toml', type=make_path, default=get_default_path(suffix='.toml'))
    subparsers = parser.add_subparsers(dest='subparser')
    parser_list = subparsers.add_parser('list-profiles', aliases=['l'])
    parser_list.set_defaults(func=list_profiles)
    add_profile_args_to_parser(parser_list, required=False)
    parser_create = subparsers.add_parser(Command.CREATE.value, aliases=['c'])
    parser_create.set_defaults(func=create)
    add_profile_args_to_parser(parser_create, required=True)
    parser_extract = subparsers.add_parser(Command.EXTRACT.value, aliases=['x'])
    parser_extract.set_defaults(func=extract)
    add_profile_args_to_parser(parser_extract, required=True)
    parser_extract.add_argument('-E', '--extract-base-dir', type=make_path, required=True)
    parser_extract.add_argument('-f', '--force', type=bool, default=False, help='Forces existing files to be overwritten without asking')
    parser_sweep = subparsers.add_parser(Command.SWEEP.value, aliases=['s'])
    parser_sweep.set_defaults(func=sweep)
    parser_sweep.add_argument('-d', '--dry-run', action=store_true)
    add_profile_args_to_parser(parser_sweep, required=True)
    args = parser.parse_args()
    args.func(args)


def add_profile_args_to_parser(parser: argparse.ArgumentParser, required: bool):
    profile_gr = parser.add_mutually_exclusive_group(required=required)
    profile_gr.add_argument('-a', '--all', action=store_true)
    profile_gr.add_argument('-p', '--profile')


def make_path(file_path: str) -> Path:
    return Path(file_path).expanduser()


def list_profiles(args):
    profile_to_settings = create_profile_to_settings_from_toml_path(args.toml)
    for profile, settings in profile_to_settings.items():
        if args.profile and profile != args.profile:
            continue
        print(f"{settings}")


def create(args):
    profile_to_settings = create_profile_to_settings_from_toml_path(args.toml)
    rumar = Rumar(profile_to_settings)
    if args.all:
        rumar.create_for_all_profiles()
    elif args.profile:
        rumar.create_for_profile(args.profile)


def extract(args):
    profile_to_settings = create_profile_to_settings_from_toml_path(args.toml)
    rumar = Rumar(profile_to_settings)
    if args.all:
        rumar.extract_for_all_profiles(extract_base_dir=args.extract_base_dir, force=args.force)
    elif args.profile:
        rumar.extract_for_profile(profile=args.profile, extract_base_dir=args.extract_base_dir, force=args.force)


def sweep(args):
    profile_to_settings = create_profile_to_settings_from_toml_path(args.toml)
    broom = Broom(profile_to_settings)
    is_dry_run = args.dry_run or False
    if args.all:
        broom.sweep_all_profiles(is_dry_run=is_dry_run)
    elif args.profile:
        broom.sweep_profile(args.profile, is_dry_run=is_dry_run)


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
      used by: create, sweep
      path to the base dir used for the profile; usually left unset; see _**backup_base_dir**_
    archive_format: Literal['tar', 'tar.gz', 'tar.bz2', 'tar.xz'] = 'tar.gz'
      used by: create, sweep
      format of archive files to be created
    compression_level: int = 3
      used by: create
      for the formats 'tar.gz', 'tar.bz2', 'tar.xz': compression level from 0 to 9
    no_compression_suffixes_default: str = '7z,zip,zipx,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,png,jpg,gif,mp4,mov,avi,mp3,m4a,aac,ogg,ogv,kdbx'
      used by: create
      comma-separated string of lower-case suffixes for which to use uncompressed tar
    no_compression_suffixes: str = ''
      used by: create
      extra lower-case suffixes in addition to _**no_compression_suffixes_default**_
    tar_format: Literal[0, 1, 2] = tarfile.GNU_FORMAT
      used by: create
      Double Commander fails to correctly display mtime when PAX is used, therefore GNU is the default
    source_dir: str
      used by: create
      path to the directory which is to be archived
    included_top_dirs: list[str]
      used by: create, sweep
      a list of paths
      if present, only files from those dirs and their descendant subdirs will be considered, together with _**included_files_as_glob**_
      the paths can be relative to _**source_dir**_ or absolute, but always under _**source_dir**_
      if missing, _**source_dir**_ and all its descendant subdirs will be considered
    excluded_top_dirs: list[str]
      used by: create, sweep
      like _**included_top_dirs**_, but for exclusion
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
      e.g. `["My Music\*.m3u"]`
      on MS Windows, global-pattern matching is case-insensitive
      caution: a leading path separator in a path/glob indicates a root directory, e.g. `["\My Music\*"]`
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
      `excluded_files_as_regex = ['/\d\d\d\d-\d\d-01_\d\d,\d\d,\d\d\.\d{6}(\+|-)\d\d,\d\d\~\d+(~.+)?.tar(\.(gz|bz2|xz))?$']`
      it's best when the setting is part of a separate profile, i.e. a copy made for _**sweep**_,
      otherwise _**create**_ will also seek such files to be excluded
    """
    profile: str
    backup_base_dir: Union[str, Path]
    source_dir: Union[str, Path]
    backup_base_dir_for_profile: Union[str, Path] = None
    included_top_dirs: Union[list[Path], set[Path], list[str], set[str]] = ()
    excluded_top_dirs: Union[list[Path], set[Path], list[str], set[str]] = ()
    included_dirs_as_regex: Union[list[str], list[Pattern]] = ()
    excluded_dirs_as_regex: Union[list[str], list[Pattern]] = ()
    included_files_as_glob: Union[list[str], set[str]] = ()
    excluded_files_as_glob: Union[list[str], set[str]] = ()
    included_files_as_regex: Union[list[str], list[Pattern]] = ()
    excluded_files_as_regex: Union[list[str], list[Pattern]] = ()
    archive_format: Union[str, RumarFormat] = RumarFormat.TGZ
    # password for zipx, as it's AES-encrypted
    password: Union[str, bytes] = None
    zip_compression_method: int = zipfile.ZIP_DEFLATED
    compression_level: int = 3
    no_compression_suffixes_default: str = (
        '7z,zip,zipx,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,'
        'xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,'
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
    commands_which_use_filters: Union[list[str], list[Command]] = (Command.CREATE,)
    COMMA = ','

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
        self.suffixes_without_compression = {f".{s}" for s in self.COMMA.join([self.no_compression_suffixes_default, self.no_compression_suffixes]).split(self.COMMA) if s}
        # https://stackoverflow.com/questions/71846054/-cast-a-string-to-an-enum-during-instantiation-of-a-dataclass-
        if self.archive_format is None:
            self.archive_format = RumarFormat.TGZ
        self.archive_format = RumarFormat(self.archive_format)
        self.commands_which_use_filters = [Command(cmd) for cmd in self.commands_which_use_filters]
        try:  # make sure password is bytes
            self.password = self.password.encode(UTF8)
        except AttributeError:  # 'bytes' object has no attribute 'encode'
            pass

    def _setify(self, attribute_name: str):
        attr = getattr(self, attribute_name)
        if attr is None:
            return set()
        setattr(self, attribute_name, set(attr))

    def _absolutopathosetify(self, attribute_name: str):
        attr = getattr(self, attribute_name)
        if attr is None:
            return set()
        lst = []
        for elem in attr:
            p = Path(elem)
            if not p.is_absolute():
                lst.append(self.source_dir / p)
            else:
                assert p.as_posix().startswith(self.source_dir.as_posix())
                lst.append(p)
        setattr(self, attribute_name, set(lst))

    def _pathlify(self, attribute_name: str):
        attr = getattr(self, attribute_name)
        if not attr:
            return attr
        if isinstance(attr, list):
            if not self.is_each_elem_of_type(attr, Path):
                setattr(self, attribute_name, [Path(elem) for elem in attr])
        else:
            if not isinstance(attr, Path):
                setattr(self, attribute_name, Path(attr))

    def _patternify(self, attribute_name: str):
        attr = getattr(self, attribute_name)
        if not attr:
            return attr
        if not isinstance(attr, list):
            raise AttributeError(f"expected a list of values, got {attr!r}")
        setattr(self, attribute_name, [re.compile(elem) for elem in attr])

    def __str__(self):
        return ("{"
                f"profile: {self.profile!r}, "
                f"backup_base_dir_for_profile: {self.backup_base_dir_for_profile.as_posix()!r}, "
                f"source_dir: {self.source_dir.as_posix()!r}"
                "}")


ProfileToSettings = dict[str, Settings]


def create_profile_to_settings_from_toml_path(toml_file: Path) -> ProfileToSettings:
    logger.log(DEBUG_11, f"{toml_file=}")
    toml_str = toml_file.read_text(encoding=UTF8)
    return create_profile_to_settings_from_toml_text(toml_str)


def create_profile_to_settings_from_toml_text(toml_str) -> ProfileToSettings:
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
    if version != 1:
        raise ValueError(f"rumar.toml version is {version} - expected 1")
    del toml_dict['version']


class CreateReason(Enum):
    NEW = '+>'
    CHANGED = '~>'


SLASH = '/'
BACKSLASH = '\\'


def iter_all_files(top_path: Path):
    for root, dirs, files in os.walk(top_path):
        for file in files:
            yield Path(root, file)


def iter_matching_files(top_path: Path, s: Settings):
    inc_dirs_rx = s.included_dirs_as_regex
    exc_dirs_rx = s.excluded_dirs_as_regex
    inc_files_rx = s.included_files_as_regex
    exc_files_rx = s.excluded_files_as_regex
    for root, dirs, files in os.walk(top_path):
        for d in dirs.copy():
            dir_path = Path(root, d)
            relative_p = make_relative_p(dir_path, top_path, with_leading_slash=True)
            if is_dir_matching_top_dirs(dir_path, relative_p, s):  # matches dirnames and/or top_dirs, now check regex
                if inc_dirs_rx:  # only included paths must be considered
                    if not find_matching_pattern(relative_p, inc_dirs_rx):
                        dirs.remove(d)
                        logger.log(DEBUG_13, f"|d ...{relative_p}  -- skipping dir: none of included_dirs_as_regex matches")
                if d in dirs and (exc_rx := find_matching_pattern(relative_p, exc_dirs_rx)):
                    dirs.remove(d)
                    logger.log(DEBUG_14, f"|d ...{relative_p}  -- skipping dir: matches '{exc_rx}'")
            else:  # doesn't match dirnames and/or top_dirs
                dirs.remove(d)
        for f in files:
            file_path = Path(root, f)
            relative_p = make_relative_p(file_path, top_path, with_leading_slash=True)
            if is_file_matching_glob(file_path, relative_p, s):  # matches glob, now check regex
                if inc_files_rx:  # only included paths must be considered
                    if not find_matching_pattern(relative_p, inc_files_rx):
                        logger.log(DEBUG_13, f"|f ...{relative_p}  -- skipping: none of included_files_as_regex matches")
                else:  # no incl filtering; checking exc_files_rx
                    if exc_rx := find_matching_pattern(relative_p, exc_files_rx):
                        logger.log(DEBUG_14, f"|f ...{relative_p}  -- skipping: matches {exc_rx!r}")
                    else:
                        yield file_path
            else:  # doesn't match glob
                pass


def is_dir_matching_top_dirs(dir_path: Path, relative_p: str, s: Settings) -> bool:
    # remove the file part by splitting at the rightmost sep, making sure not to split at the root sep
    inc_file_dirnames_as_glob = {f.rsplit(sep, 1)[0] for f in s.included_files_as_glob if (sep := find_sep(f)) and sep in f.lstrip(sep)}
    inc_top_dirs_psx = [p.as_posix() for p in s.included_top_dirs]
    exc_top_dirs_psx = [p.as_posix() for p in s.excluded_top_dirs]
    dir_path_psx = dir_path.as_posix()
    for exc_top_psx in exc_top_dirs_psx:
        if dir_path_psx.startswith(exc_top_psx):
            logger.log(DEBUG_14, f"|D ...{relative_p}  -- skipping: matches excluded_top_dirs")
            return False
    if not (s.included_top_dirs or s.included_files_as_glob):
        logger.log(DEBUG_11, f"=D ...{relative_p}  -- including all: no included_top_dirs or included_files_as_glob")
        return True
    for dirname_glob in inc_file_dirnames_as_glob:
        if dir_path.match(dirname_glob):
            logger.log(DEBUG_12, f"=D ...{relative_p}  -- matches included_file_as_glob's dirname")
            return True
    for inc_top_psx in inc_top_dirs_psx:
        if dir_path_psx.startswith(inc_top_psx) or inc_top_psx.startswith(dir_path_psx):
            logger.log(DEBUG_12, f"=D ...{relative_p}  -- matches included_top_dirs")
            return True
    logger.log(DEBUG_13, f"|D ...{relative_p}  -- skipping: doesn't match dirnames and/or top_dirs")
    return False


def is_file_matching_glob(file_path: Path, relative_p: str, s: Settings) -> bool:
    inc_top_dirs_psx = [p.as_posix() for p in s.included_top_dirs]
    inc_files = s.included_files_as_glob
    exc_files = s.excluded_files_as_glob
    file_path_psx = file_path.as_posix()
    # interestingly, the following expression doesn't have the same effect as the below for-loops - why?
    # not any(file_path.match(file_as_glob) for file_as_glob in exc_files) and (
    #         any(file_path.match(file_as_glob) for file_as_glob in inc_files)
    #         or any(file_path_psx.startswith(top_dir) for top_dir in inc_top_dirs_psx)
    # )
    for file_as_glob in exc_files:
        if file_path.match(file_as_glob):
            logger.log(DEBUG_14, f"|F ...{relative_p}  -- skipping: matches excluded_files_as_glob {file_as_glob!r}")
            return False
    if not (s.included_top_dirs or s.included_files_as_glob):
        logger.log(DEBUG_11, f"=F ...{relative_p}  -- including all: no included_top_dirs or included_files_as_glob")
        return True
    for file_as_glob in inc_files:
        if file_path.match(file_as_glob):
            logger.log(DEBUG_12, f"=F ...{relative_p}  -- matches included_files_as_glob {file_as_glob!r}")
            return True
    for inc_top_psx in inc_top_dirs_psx:
        if file_path_psx.startswith(inc_top_psx):
            logger.log(DEBUG_12, f"=F ...{relative_p}  -- matches included_top_dirs {inc_top_psx!r}")
            return True
    logger.log(DEBUG_13, f"|F ...{relative_p}  -- skipping file: doesn't match top dir or file glob")
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


def make_relative_p(path: Path, base_dir: Path, with_leading_slash=False) -> str:
    relative_p = path.as_posix().removeprefix(base_dir.as_posix())
    return relative_p.removeprefix(SLASH) if not with_leading_slash else relative_p


def find_matching_pattern(relative_p: str, patterns: list[Pattern]):
    # logger.debug(f"{relative_p}, {[p.pattern for p in patterns]}")
    for rx in patterns:
        if rx.search(relative_p):
            return rx.pattern


def sorted_files_by_stem_then_suffix_ignoring_case(matching_files: Iterable[Path]):
    """sort by stem then suffix, i.e. 'abc.txt' before 'abc(2).txt'; ignore case"""
    return sorted(matching_files, key=lambda x: (x.stem.lower(), x.suffix.lower()))


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
    RX_ARCHIVE_SUFFIX = re.compile(r'\.(tar(\.(gz|bz2|xz))?|zipx)$')
    CHECKSUM_SUFFIX = '.b2'
    CHECKSUM_SIZE_THRESHOLD = 10_000_000
    STEMS = 'stems'
    PATHS = 'paths'

    def __init__(self, profile_to_settings: ProfileToSettings):
        self._profile_to_settings = profile_to_settings
        self._profile: Optional[str] = None
        self._suffix_size_stems_and_paths: dict[str, dict[int, dict]] = {}
        self._path_to_lstat: dict[Path, os.stat_result] = {}
        self._warnings = []
        self._errors = []

    @staticmethod
    def can_ignore_for_archive(lstat: os.stat_result) -> bool:
        mode = lstat.st_mode
        return stat.S_ISSOCK(mode) or stat.S_ISDOOR(mode)

    @staticmethod
    def find_last_file_in_dir(archive_container_dir: Path, pattern: Pattern = None) -> Optional[os.DirEntry]:
        for dir_entry in sorted(os.scandir(archive_container_dir), key=lambda x: x.name, reverse=True):
            if dir_entry.is_file():
                if pattern is None:
                    return dir_entry
                elif pattern.search(dir_entry.name):
                    return dir_entry

    @staticmethod
    def compute_checksum_of_file_in_archive(archive: Path, password: bytes) -> str:
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
    def to_mtime_str(cls, dt: datetime) -> str:
        """archive-file stem - first part"""
        if dt.utcoffset() is None:
            dt = dt.astimezone()
        return dt.astimezone().isoformat().replace(cls.COLON, cls.COMMA).replace(cls.T, cls.UNDERSCORE)

    @classmethod
    def from_mtime_str(cls, s: str) -> datetime:
        return datetime.fromisoformat(s.replace(cls.UNDERSCORE, cls.T).replace(cls.COMMA, cls.COLON))

    @classmethod
    def calc_checksum_file_path(cls, archive_path: Path) -> Path:
        core = cls.extract_core(archive_path.name)
        return archive_path.with_name(f"{core}{cls.CHECKSUM_SUFFIX}")

    @classmethod
    def extract_mtime_size(cls, archive_path: Optional[Path]) -> Optional[tuple[str, int]]:
        if archive_path is None:
            return None
        core = cls.extract_core(archive_path.name)
        return cls.split_mtime_size(core)

    @classmethod
    def extract_core(cls, basename: str) -> str:
        """Example: 2023-04-30_09,48,20.872144+02,00~123#a7b6de.tar.gz => 2023-04-30_09,48,20+02,00~123#a7b6de"""
        core = cls.RX_ARCHIVE_SUFFIX.sub('', basename)
        if core == basename:
            raise RuntimeError('basename: ' + basename)
        return core

    @classmethod
    def split_ext(cls, basename: str) -> tuple[str, str]:
        """Example: 2023-04-30_09,48,20.872144+02,00~123.tar.gz => 2023-04-30_09,48,20+02,00~123 .gz"""
        raise NotImplementedError('this method needs work after the addition of zipx')
        try:
            core, post_tar_ext = basename.rsplit(cls.DOT_TAR, 1)
        except ValueError:
            print(basename)
            raise
        return core, f"{cls.DOT_TAR}{post_tar_ext}"

    @classmethod
    def split_mtime_size(cls, core: str) -> tuple[str, int]:
        """Example: 2023-04-30_09,48,20.872144+02,00~123~ab12~LNK => 2023-04-30_09,48,20.872144+02,00 123 ab12 LNK"""
        split_result = core.split(cls.MTIME_SEP)
        mtime_str = split_result[0]
        size = int(split_result[1])
        return mtime_str, size

    @classmethod
    def calc_archive_path(cls, archive_container_dir: Path, archive_format: RumarFormat, mtime_str: str, size: int, comment: str = None) -> Path:
        return archive_container_dir / f"{mtime_str}{cls.MTIME_SEP}{size}{cls.MTIME_SEP + comment if comment else cls.BLANK}.{archive_format.value}"

    @property
    def s(self) -> Settings:
        return self._profile_to_settings[self._profile]

    def cached_lstat(self, path: Path):
        return self._path_to_lstat.setdefault(path, path.lstat())

    def create_for_all_profiles(self):
        for profile in self._profile_to_settings:
            self.create_for_profile(profile)

    def create_for_profile(self, profile: str):
        """Create a backup for the specified profile
        """
        logger.info(f"{profile=}")
        self._at_beginning(profile)
        for p in self.source_files:
            relative_p = make_relative_p(p, self.s.source_dir)
            lstat = self.cached_lstat(p)  # don't follow symlinks - pathlib calls stat for each is_*()
            mtime = lstat.st_mtime
            mtime_dt = datetime.fromtimestamp(mtime).astimezone()
            mtime_str = self.to_mtime_str(mtime_dt)
            size = lstat.st_size
            latest_archive = self._find_latest_archive(relative_p)
            latest = self.extract_mtime_size(latest_archive)
            archive_container_dir = self.calc_archive_container_dir(relative_p=relative_p)
            if latest is None:
                # no previous backup found
                self._create(CreateReason.NEW, p, relative_p, archive_container_dir, mtime_str, size)
            else:
                latest_mtime_str, latest_size = latest
                latest_mtime_dt = self.from_mtime_str(latest_mtime_str)
                is_changed = False
                if mtime_dt > latest_mtime_dt:
                    if size != latest_size:
                        is_changed = True
                    else:
                        is_changed = False
                        if self.s.checksum_comparison_if_same_size:
                            # get checksum of the latest archived file (unpacked)
                            checksum_file = self.calc_checksum_file_path(latest_archive)
                            if not checksum_file.exists():
                                latest_checksum = self.compute_checksum_of_file_in_archive(latest_archive, self.s.password)
                                logger.info(f':- {relative_p}  {latest_mtime_str}  {latest_checksum}')
                                checksum_file.write_text(latest_checksum)
                            else:
                                latest_checksum = checksum_file.read_text()
                            # get checksum of the current file
                            with p.open('rb') as f:
                                checksum = compute_blake2b_checksum(f)
                            self._save_checksum_if_big(size, checksum, relative_p, archive_container_dir, mtime_str)
                            is_changed = checksum != latest_checksum
                        else:
                            pass
                            # newer mtime, same size, not instructed to do checksum comparison => no backup
                if is_changed:
                    # file has changed as compared to the last backup
                    logger.info(f":= {relative_p}  {latest_mtime_str}  {latest_size} =: last backup")
                    self._create(CreateReason.CHANGED, p, relative_p, archive_container_dir, mtime_str, size)
        self._at_end()

    def _at_beginning(self, profile: str):
        self._profile = profile  # for self.s to work
        self._path_to_lstat.clear()
        self._warnings.clear()
        self._errors.clear()

    def _at_end(self):
        self._profile = None  # safeguard so that self.s will complain
        if self._warnings:
            for w in self._warnings:
                logger.warning(w)
        if self._errors:
            for e in self._errors:
                logger.error(e)

    def _save_checksum_if_big(self, size, checksum, relative_p, archive_container_dir, mtime_str):
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
            checksum_file = archive_container_dir / f"{mtime_str}{self.MTIME_SEP}{size}{self.CHECKSUM_SUFFIX}"
            logger.info(f':  {relative_p}  {checksum}')
            archive_container_dir.mkdir(parents=True, exist_ok=True)
            checksum_file.write_text(checksum)

    def _find_latest_archive(self, relative_p: str) -> Optional[Path]:
        archive_container_dir = self.calc_archive_container_dir(relative_p=relative_p)
        if not archive_container_dir.exists():
            return None
        latest_dir_entry = self.find_last_file_in_dir(archive_container_dir, self.RX_ARCHIVE_SUFFIX)
        return Path(latest_dir_entry) if latest_dir_entry else None

    def _create(self, create_reason: CreateReason, path: Path, relative_p: str, archive_container_dir: Path, mtime_str: str, size: int):
        if self.s.archive_format == RumarFormat.ZIPX:
            self._create_zipx(create_reason, path, relative_p, archive_container_dir, mtime_str, size)
        else:
            self._create_tar(create_reason, path, relative_p, archive_container_dir, mtime_str, size)

    def _create_tar(self, create_reason: CreateReason, path: Path, relative_p: str, archive_container_dir: Path, mtime_str: str, size: int):
        archive_container_dir.mkdir(parents=True, exist_ok=True)
        sign = create_reason.value
        logger.info(f"{sign} {relative_p}  {mtime_str}  {size} {sign} {archive_container_dir}")
        archive_format, compresslevel_kwargs = self.calc_archive_format_and_compresslevel_kwargs(path)
        mode = self.ARCHIVE_FORMAT_TO_MODE[archive_format]
        is_lnk = stat.S_ISLNK(self.cached_lstat(path).st_mode)
        archive_path = self.calc_archive_path(archive_container_dir, archive_format, mtime_str, size, self.LNK if is_lnk else self.BLANK)
        with tarfile.open(archive_path, mode, format=self.s.tar_format, **compresslevel_kwargs) as tf:
            tf.add(path, arcname=path.name)

    def _create_zipx(self, create_reason: CreateReason, path: Path, relative_p: str, archive_container_dir: Path, mtime_str: str, size: int):
        archive_container_dir.mkdir(parents=True, exist_ok=True)
        sign = create_reason.value
        logger.info(f"{sign} {relative_p}  {mtime_str}  {size} {sign} {archive_container_dir}")
        if path.suffix.lower() in self.s.suffixes_without_compression:
            kwargs = {self.COMPRESSION: zipfile.ZIP_STORED}
        else:
            kwargs = {self.COMPRESSION: self.s.zip_compression_method, self.COMPRESSLEVEL: self.s.compression_level}
        is_lnk = stat.S_ISLNK(self.cached_lstat(path).st_mode)
        archive_path = self.calc_archive_path(archive_container_dir, RumarFormat.ZIPX, mtime_str, size, self.LNK if is_lnk else self.BLANK)
        with pyzipper.AESZipFile(archive_path, 'w', encryption=pyzipper.WZ_AES, **kwargs) as zf:
            zf.setpassword(self.s.password)
            zf.write(path, arcname=path.name)

    def calc_archive_container_dir(self, *, relative_p: Optional[str] = None, path: Optional[Path] = None) -> Path:
        assert relative_p or path, '** either relative_p or path must be provided'
        if not relative_p:
            relative_p = make_relative_p(path, self.s.source_dir)
        return self.s.backup_base_dir_for_profile / relative_p

    def calc_archive_format_and_compresslevel_kwargs(self, path: Path) -> tuple[RumarFormat, dict]:
        if (
                path.is_absolute() and  # for gardner.repack, which has only arc_name
                stat.S_ISLNK(self.cached_lstat(path).st_mode)
        ):
            return self.SYMLINK_FORMAT_COMPRESSLEVEL
        elif path.suffix.lower() in self.s.suffixes_without_compression or self.s.archive_format == RumarFormat.TAR:
            return self.NOCOMPRESSION_FORMAT_COMPRESSLEVEL
        else:
            key = self.PRESET if self.s.archive_format == RumarFormat.TXZ else self.COMPRESSLEVEL
            return self.s.archive_format, {key: self.s.compression_level}

    @property
    def source_files(self):
        return self.create_optionally_deduped_list_of_matching_files(self.s.source_dir, self.s)

    def create_optionally_deduped_list_of_matching_files(self, top_path: Path, s: Settings):
        matching_files = []
        # the make-iterator logic is not extracted to a function so that logger prints the calling function's name
        if Command.CREATE in s.commands_which_use_filters:
            iterator = iter_matching_files(top_path, s)
            logger.debug(f"{s.commands_which_use_filters=} => iter_matching_files")
        else:
            iterator = iter_all_files(top_path)
            logger.debug(f"{s.commands_which_use_filters=} => iter_all_files")
        for file_path in iterator:
            lstat = self.cached_lstat(file_path)
            if self.can_ignore_for_archive(lstat):
                logger.info(f"-| {file_path}  -- ignoring file for archiving: socket/door")
                continue
            if s.file_deduplication and (duplicate := self.find_duplicate(file_path)):
                logger.info(f"{make_relative_p(file_path, top_path)!r} -- skipping: duplicate of {make_relative_p(duplicate, top_path)!r}")
                continue
            matching_files.append(file_path)
        return sorted_files_by_stem_then_suffix_ignoring_case(matching_files)

    def find_duplicate(self, file_path: Path) -> Optional[Path]:
        """
        a duplicate file has the same suffix and size and part of its name, case-insensitive (suffix, name)
        """
        stem, suffix = os.path.splitext(file_path.name.lower())
        size = self.cached_lstat(file_path).st_size
        if size_to_stems_and_paths := self._suffix_size_stems_and_paths.get(suffix):
            if stems_and_paths := size_to_stems_and_paths.get(size):
                if stems_and_paths:
                    stems = stems_and_paths[self.STEMS]
                    for index, s in enumerate(stems):
                        if stem in s or s in stem:
                            return stems_and_paths[self.PATHS][index]
        # no record; create one
        stems_and_paths = self._suffix_size_stems_and_paths.setdefault(suffix, {}).setdefault(size, {})
        stems_and_paths.setdefault(self.STEMS, []).append(stem)
        stems_and_paths.setdefault(self.PATHS, []).append(file_path)

    def extract_for_all_profiles(self, extract_base_dir: Path, force: bool):
        for profile in self._profile_to_settings:
            self.extract_for_profile(profile, extract_base_dir, force)

    def extract_for_profile(self, profile: str, extract_base_dir: Path, force: bool):
        # extract latest to root
        logger.info(f"{profile=} extract_base_dir={repr(str(extract_base_dir))} {force=}")
        self._at_beginning(profile)
        for dirpath, dirnames, filenames in os.walk(self.s.backup_base_dir_for_profile):
            archive_container_dir = Path(dirpath)  # the original file, in the mirrored directory tree
            relative_file_parent = make_relative_p(archive_container_dir.parent, self.s.backup_base_dir_for_profile)
            target_file = extract_base_dir / relative_file_parent / archive_container_dir.name
            if filenames:
                if target_file.exists():
                    if force or self._ask_to_overwrite(target_file):
                        should_extract = True
                    else:
                        should_extract = False
                        warning = f"file exists - skipping  {target_file}"
                        self._warnings.append(warning)
                        logger.warning(warning)
                else:
                    should_extract = True
                if should_extract:
                    for f in sorted(filenames, reverse=True):
                        if self.RX_ARCHIVE_SUFFIX.search(f):
                            archive_path = archive_container_dir / f
                            self._extract(archive_path, target_file)
                            break
        self._at_end()

    @staticmethod
    def _ask_to_overwrite(target_file):
        answer = input(f"\n{target_file}\n The above file exists. Overwrite it? [y/N] ")
        logger.info(f":  {answer=}  {target_file}")
        return answer in ['y', 'Y']

    def _extract(self, file: Path, target_file: Path):
        if file.suffix == self.DOT_ZIPX:
            self._extract_zipx(file, target_file)
        else:
            self._extract_tar(file, target_file)

    def _extract_zipx(self, file: Path, target_file: Path):
        logger.info(f":@ {file.parent.name} | {file.name}")
        with pyzipper.AESZipFile(file) as zf:
            zf.setpassword(self.s.password)
            member = cast(zipfile.ZipInfo, zf.infolist()[0])
            if member.filename == target_file.name:
                zf.extract(member, target_file.parent)
                mtime_str, size = self.extract_mtime_size(file)
                self.set_mtime(target_file, self.from_mtime_str(mtime_str))
            else:
                error = f"archived-file name is different than the archive-container-directory name: {member.filename} != {target_file.name}"
                self._errors.append(error)
                logger.error(error)

    def _extract_tar(self, file: PathAlike, target_directory: PathAlike):
        raise NotImplementedError()


def compute_blake2b_checksum(f: BinaryIO) -> str:
    b = blake2b()
    for chunk in iter(lambda: f.read(32768), b''):
        b.update(chunk)
    return b.hexdigest()


class Broom:
    DASH = '-'
    DOT = '.'

    def __init__(self, profile_to_settings: ProfileToSettings):
        self._profile_to_settings = profile_to_settings
        self._db = BroomDB()

    @classmethod
    def is_archive(cls, name: str, archive_format: str) -> bool:
        return (name.endswith(cls.DOT + archive_format) or
                name.endswith(cls.DOT + RumarFormat.TAR.value))

    @staticmethod
    def is_checksum(name: str) -> bool:
        return name.endswith(Rumar.CHECKSUM_SUFFIX)

    @classmethod
    def extract_date_from_name(cls, name: str) -> date:
        iso_date_string = name[:10]
        y, m, d = iso_date_string.split(cls.DASH)
        return date(int(y), int(m), int(d))

    def sweep_all_profiles(self, *, is_dry_run: bool):
        for profile in self._profile_to_settings:
            self.sweep_profile(profile, is_dry_run=is_dry_run)

    def sweep_profile(self, profile, *, is_dry_run: bool):
        logger.info(profile)
        s = self._profile_to_settings[profile]
        self.gather_info(s)
        self.delete_files(is_dry_run)

    def gather_info(self, s: Settings):
        archive_format = RumarFormat(s.archive_format).value
        date_older_than_x_days = date.today() - timedelta(days=s.min_age_in_days_of_backups_to_sweep)
        # the make-iterator logic is not extracted to a function so that logger prints the calling function's name
        if Command.SWEEP in s.commands_which_use_filters:
            iterator = iter_matching_files(s.backup_base_dir_for_profile, s)
            logger.debug(f"{s.commands_which_use_filters=} => iter_matching_files")
        else:
            iterator = iter_all_files(s.backup_base_dir_for_profile)
            logger.debug(f"{s.commands_which_use_filters=} => iter_all_files")
        old_enough_file_to_mdate = {}
        for path in iterator:
            if self.is_archive(path.name, archive_format):
                mdate = self.extract_date_from_name(path.name)
                if mdate <= date_older_than_x_days:
                    old_enough_file_to_mdate[path] = mdate
            elif not self.is_checksum(path.name):
                logger.warning(f":! {path.as_posix()}  is unexpected (not an archive)")
        for path in sorted_files_by_stem_then_suffix_ignoring_case(old_enough_file_to_mdate):
            self._db.insert(path, mdate=old_enough_file_to_mdate[path])
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

    def iter_marked_for_removal(self) -> Iterator[tuple[str, str, str, str, str, str, str, str]]:
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
