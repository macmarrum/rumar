#!/usr/bin/python3
import argparse
import logging
import os
import re
import sqlite3
import stat
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from enum import Enum
from hashlib import sha256
from pathlib import Path
from textwrap import dedent
from types import TracebackType
from typing import Iterator, Union, Optional, Literal, Pattern, Any

vi = sys.version_info
assert (vi.major, vi.minor) >= (3, 9), 'expected Python 3.9 or higher'

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print('use Python version >= 3.11 or install the module "tomli"')
        raise

me = Path(__file__)

# <logger>

DEBUG_11 = 11
DEBUG_15 = 15
DEBUG_16 = RETVAL_16 = 16
DEBUG_17 = METHOD_17 = 17
LEVEL_TO_SHORT = {
    10: '>>',  # DEBUG
    11: '>+',  # DEBUG11
    15: '>:',  # DEBUG15
    16: '=>',  # RETVAL
    17: '~~',  # METHOD
    20: '::',  # INFO
    30: '*=',  # WARNING
    40: '**',  # ERROR
    50: '##'  # CRITICAL
}
SHORT_DEFAULT = '--'

logging.addLevelName(DEBUG_11, 'DEBUG_11')
logging.addLevelName(DEBUG_15, 'DEBUG_15')
logging.addLevelName(DEBUG_16, 'DEBUG_16')
logging.addLevelName(DEBUG_17, 'DEBUG_17')


class MyLogger(logging.Logger):
    def __init__(self, name, level=logging.NOTSET):
        super().__init__(name, level)

    def makeRecord(self, name: str, level: int, fn: str, lno: int, msg: Any,
                   args: Union[tuple[Any, ...], dict[str, Any]],
                   exc_info: Optional[
                       Union[tuple[type, BaseException, Optional[TracebackType]], tuple[None, None, None]]],
                   func: Optional[str] = ..., extra: Optional[dict[str, Any]] = ...,
                   sinfo: Optional[str] = ...) -> logging.LogRecord:
        """override
        Add 'levelShort' field to LogRecord, to be used in 'format'
        """
        log_record = super().makeRecord(name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)
        log_record.levelShort = LEVEL_TO_SHORT.get(level, SHORT_DEFAULT)
        return log_record


logger = MyLogger(me.name)
log_level = logging.DEBUG
filename = me.with_suffix('.log')
log_format = '{levelShort} {asctime}: {funcName:20} {msg}'
# log_format = '{msg}'
formatter = logging.Formatter(log_format, style='{')
# for console output
to_console = logging.StreamHandler()
to_console.setLevel(log_level)
to_console.setFormatter(formatter)
logger.addHandler(to_console)
# for file output
to_file = logging.FileHandler(filename=filename, encoding='UTF-8')
to_file.setLevel(log_level)
to_file.setFormatter(formatter)
logger.addHandler(to_file)

# </logger>


store_true = 'store_true'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--toml', type=make_path, default=get_default_path(suffix='.toml'))
    subparsers = parser.add_subparsers(dest='subparser')
    parser_list = subparsers.add_parser('list-profiles', aliases=['l'])
    parser_list.set_defaults(func=list_profiles)
    add_profile_args_to_parser(parser_list, required=False)
    parser_create = subparsers.add_parser('create', aliases=['c'])
    parser_create.set_defaults(func=create)
    add_profile_args_to_parser(parser_create, required=True)
    parser_extract = subparsers.add_parser('extract', aliases=['x'])
    parser_extract.set_defaults(func=extract)
    add_profile_args_to_parser(parser_extract, required=True)
    parser_extract.add_argument('-e', '--extract-root', type=make_path, required=True)
    parser_sweep = subparsers.add_parser('sweep')
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
    print('** extract not implemented')


def sweep(args):
    profile_to_settings = create_profile_to_settings_from_toml_path(args.toml)
    broom = Broom(profile_to_settings)
    if args.all:
        broom.sweep_all_profiles()
    elif args.profile:
        broom.sweep_profile(args.profile)


class RumarFormat(Enum):
    TAR = 'tar'
    TGZ = 'tar.gz'
    TBZ = 'tar.bz2'
    TXZ = 'tar.xz'


@dataclass
class Settings:
    """
    profile: str
      name of the profile
    backup_base_dir: str
      path to the base directory used for backup; usually set in the global space, common for all profiles
      backup dir for each profile is constructed as backup_base_dir + profile, unless backup_base_dir_for_profile is set, which takes precedence
    backup_base_dir_for_profile: str = None
      path to the base dir used for the profile; usually left unset; see backup_base_dir
    archive_format: Literal[tar, tar.gz, tar.bz2, tar.xz] = 'tar.gz'
        archive file to be created
    compression_level: int = 3
        for formats tgz, tbz, txz: compression level from 0 to 9
    no_compression_suffixes_default: str = '7z,zip,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,png,jpg,mp4,mov,mp3,m4a,aac,ogg,ogv,kdbx'
        comma-separated string of lower-case suffixes for which to use uncompressed tar
    no_compression_suffixes: str = ''
        extra lower-case suffixes in addition to no_compression_suffixes_default
    tar_format: Literal[0, 1, 2] = tarfile.GNU_FORMAT
      DoubleCmd fails to correctly display mtime when PAX is used – GNU is recommended
    source_dir: str
      path to the root directory that is to be archived
    source_files: Optional[list[str]]
      if present, only these files are considered
      can be relative to source_dir or absolute (but under source_dir)
      on Windows, if absolute, must use the source_dir-drive-letter case (upper or lower)
    excluded_files_as_regex, excluded_dirs_as_regex: Optional[list[str]]
      regex defining files or dirs (recursively) to be excluded, relative to source_dir
      must use / also on Windows
      the first segment in the relative path (to match against) also starts with a slash
      e.g. ['/B$',] will exclude any basename equal to B, at any level
    sha256_comparison_if_same_size: bool = False
      when False, a file is considered changed if its mtime is later than the latest backup's mtime and its size changed
      when True, SHA256 checksum is compared to determine if the file changed despite having the same size
    age_threshold_of_backups_to_sweep: int = 2
      when `sweep` is used, consider for removal only such backups which are older than X days
    number_of_daily_backups_to_keep: int = 2
    number_of_weekly_backups_to_keep: int = 14
    number_of_monthly_backups_to_keep: int = 60
      when `sweep` is used, remove backups if their number per file is above the setting per day and week and month
    """
    profile: str
    backup_base_dir: Union[str, Path]
    source_dir: Union[str, Path]
    backup_base_dir_for_profile: Union[str, Path] = None
    included_dirs_as_glob: list[str] = ()
    included_files_as_glob: list[str] = ()
    excluded_dirs_as_glob: list[str] = ()
    excluded_files_as_glob: list[str] = ()
    included_dirs_as_regex: Union[list[str], list[Pattern]] = ()
    included_files_as_regex: Union[list[str], list[Pattern]] = ()
    excluded_dirs_as_regex: Union[list[str], list[Pattern]] = ()
    excluded_files_as_regex: Union[list[str], list[Pattern]] = ()
    archive_format: Union[str, RumarFormat] = RumarFormat.TGZ
    compression_level: int = 3
    no_compression_suffixes_default: str = (
        '7z,zip,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,'
        'xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,'
        'png,jpg,mp4,mov,mp3,m4a,aac,ogg,ogv,kdbx'
    )
    no_compression_suffixes: str = ''
    tar_format: Literal[0, 1, 2] = tarfile.GNU_FORMAT
    sha256_comparison_if_same_size: bool = False
    skip_duplicate_files: bool = False
    age_threshold_of_backups_to_sweep: int = 2
    number_of_daily_backups_to_keep: int = 2
    number_of_weekly_backups_to_keep: int = 14
    number_of_monthly_backups_to_keep: int = 60
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
        self._patternify('excluded_dirs_as_regex')
        self._patternify('excluded_files_as_regex')
        self.suffixes_without_compression = {f".{s}" for s in self.COMMA.join([self.no_compression_suffixes_default, self.no_compression_suffixes]).split(self.COMMA) if s}
        # https://stackoverflow.com/questions/71846054/-cast-a-string-to-an-enum-during-instantiation-of-a-dataclass-
        if self.archive_format is None:
            self.archive_format = RumarFormat.TGZ
        self.archive_format = RumarFormat(self.archive_format)

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
    toml_str = toml_file.read_text(encoding='UTF-8')
    return create_profile_to_settings_from_toml_text(toml_str)


def create_profile_to_settings_from_toml_text(toml_str) -> ProfileToSettings:
    profile_to_settings: ProfileToSettings = {}
    toml_dict = tomllib.loads(toml_str)
    common_kwargs_for_settings = {}
    profile_to_dict = {}
    for key, value in toml_dict.items():
        if isinstance(value, dict):
            profile_to_dict[key] = value
        else:
            common_kwargs_for_settings[key] = value
    for profile, dct in profile_to_dict.items():
        kwargs_for_settings = common_kwargs_for_settings.copy()
        kwargs_for_settings['profile'] = profile
        for key, value in dct.items():
            kwargs_for_settings[key] = value
        profile_to_settings[profile] = Settings(**kwargs_for_settings)
    return profile_to_settings


class CreateReason(Enum):
    NEW = '+>'
    CHANGED = '~>'


def iter_matching_files(top_path: Path, s: Settings):
    inc_dirs = s.included_dirs_as_glob
    inc_files = s.included_files_as_glob
    exc_dirs = s.excluded_dirs_as_glob
    exc_files = s.excluded_files_as_glob
    inc_dirs_rx = s.included_dirs_as_regex
    inc_files_rx = s.included_files_as_regex
    exc_dirs_rx = s.excluded_dirs_as_regex
    exc_files_rx = s.excluded_files_as_regex
    for root, dirs, files in os.walk(top_path):
        for d in dirs:
            dir_path = Path(root, d)
            if (
                    (any(dir_path.match(dir_as_glob) for dir_as_glob in inc_dirs) if inc_dirs else True)
                    and not any(dir_path.match(dir_as_glob) for dir_as_glob in exc_dirs)
            ):  # matches glob, now check regex
                relative_p = make_relative_p(dir_path, top_path)
                if inc_dirs_rx:  # only included paths must be considered
                    if not find_matching_pattern(relative_p, inc_dirs_rx):
                        dirs.remove(d)
                        logger.debug(f"|| ...{relative_p}  -- skipping dir: none of included_dirs_as_regex matches")
                if exc_rx := find_matching_pattern(relative_p, exc_dirs_rx):
                    dirs.remove(d)
                    logger.debug(f"|| ...{relative_p}  -- skipping dir: matches '{exc_rx}'")
            else:  # doesn't match glob
                dirs.remove(d)
        for f in files:
            file_path = Path(root, f)
            if (
                    (any(file_path.match(file_as_glob) for file_as_glob in inc_files) if inc_files else True)
                    and not any(file_path.match(file_as_glob) for file_as_glob in exc_files)
            ):  # matches glob, now check regex
                relative_p = make_relative_p(file_path, top_path)
                if inc_files_rx:  # only included paths must be considered
                    if not find_matching_pattern(relative_p, inc_files_rx):
                        logger.debug(f"-- ...{relative_p}  -- skipping: none of included_files_as_regex matches")
                else:  # no incl filtering; checking exc_files_rx
                    if exc_rx := find_matching_pattern(relative_p, exc_files_rx):
                        logger.debug(f"|| ...{relative_p}  -- skipping: matches {exc_rx!r}")
                    else:
                        yield file_path
            else:  # doesn't match glob
                pass


def make_relative_p(path: Path, base_dir: Path = None) -> str:
    return path.as_posix().removeprefix(base_dir.as_posix()).removeprefix('/')


def find_matching_pattern(relative_p: str, patterns: list[Pattern]):
    for rx in patterns:
        if rx.search(relative_p):
            return rx.pattern


class Rumar:
    """
    Creates a directory named as the original file, containing a tarred copy of the file, optionally compressed.
    Files are added to the tar archive only if they were changed (mtime, size), as compared to the last archive.
    The archive-container directory is placed in a mirrored directory hierarchy.
    """
    BLANK = ''
    RX_NONE = re.compile('')
    SLASH = '/'
    MTIME_SEP = '~'
    COLON = ':'
    COMMA = ','
    T = 'T'
    UNDERSCORE = '_'
    DOT_TAR = '.tar'
    SYMLINK_COMPRESSLEVEL = 3
    COMPRESSLEVEL = 'compresslevel'
    PRESET = 'preset'
    SYMLINK_FORMAT_COMPRESSLEVEL = RumarFormat.TGZ, {COMPRESSLEVEL: SYMLINK_COMPRESSLEVEL}
    NOCOMPRESSION_FORMAT_COMPRESSLEVEL = RumarFormat.TAR, {}
    LNK = 'LNK'
    ARCHIVE_FORMAT_TO_MODE = {RumarFormat.TAR: 'x', RumarFormat.TGZ: 'x:gz', RumarFormat.TBZ: 'x:bz2', RumarFormat.TXZ: 'x:xz'}
    RX_TAR = re.compile(r'\.tar(\.(gz|bz2|xz))?$')
    CHECKSUM_SUFFIX = '.sha256'
    _path_to_lstat: dict[Path, os.stat_result] = {}
    STEMS = 'stems'
    PATHS = 'paths'

    def __init__(self, profile_to_settings: ProfileToSettings):
        self._profile_to_settings = profile_to_settings
        self._profile: Optional[str] = None
        self._suffix_size_stems_and_paths: dict[str, dict[int, dict]] = {}

    @classmethod
    def cached_lstat(cls, path: Path):
        return cls._path_to_lstat.setdefault(path, path.lstat())

    @classmethod
    def to_mtime_str(cls, dt: datetime) -> str:
        """archive-file stem - first part"""
        if dt.utcoffset() is None:
            dt = dt.astimezone()
        return dt.astimezone().isoformat().replace(cls.COLON, cls.COMMA).replace(cls.T, cls.UNDERSCORE)

    @classmethod
    def from_mtime_str(cls, s: str) -> datetime:
        return datetime.fromisoformat(s.replace(cls.UNDERSCORE, cls.T).replace(cls.COMMA, cls.COLON))

    @property
    def s(self) -> Settings:
        return self._profile_to_settings[self._profile]

    def create_for_all_profiles(self):
        for profile in self._profile_to_settings:
            self.create_for_profile(profile)

    def create_for_profile(self, profile: str):
        """Create a backup for the specified profile
        """
        self._profile = profile  # for self.s to work
        for p in self.source_files:
            relative_p = make_relative_p(p, self.s.source_dir)
            lstat = self.cached_lstat(p)  # don't follow symlinks - pathlib calls stat for each is_*()
            if self.should_ignore_for_archive(lstat):
                logger.info(f"-| {p}  -- ignoring file for archiving: socket/door")
                continue
            mtime = lstat.st_mtime
            mtime_dt = datetime.fromtimestamp(mtime).astimezone()
            mtime_str = self.to_mtime_str(mtime_dt)
            size = lstat.st_size
            latest_archive = self.get_latest_archive(relative_p)
            latest = self.extract_mtime_size(latest_archive)
            archive_container_dir = self.compile_archive_container_dir(relative_p=relative_p)
            if latest is None:
                # no previous backup found
                self._create(CreateReason.NEW, p, relative_p, archive_container_dir, mtime_str, size)
            else:
                latest_mtime_str, latest_size = latest
                latest_mtime_dt = self.from_mtime_str(latest_mtime_str)
                is_changed = False
                checksum = None
                if mtime_dt > latest_mtime_dt:
                    if size != latest_size:
                        is_changed = True
                    else:
                        is_changed = False
                        if self.s.sha256_comparison_if_same_size:
                            checksum_file = self.get_checksum_file_path(latest_archive)
                            if not checksum_file.exists():
                                latest_checksum = self.compute_checksum_of_file_in_archive(latest_archive)
                                logger.info(f':- {relative_p}  {latest_mtime_str}  {latest_checksum}')
                                checksum_file.write_text(latest_checksum)
                            else:
                                latest_checksum = checksum_file.read_text()
                            checksum = sha256(p.open('rb').read()).hexdigest()
                            is_changed = checksum != latest_checksum
                        else:
                            pass
                            # newer mtime, same size, not instructed to do checksum comparison => no backup
                if is_changed:
                    if checksum:  # save checksum, if it was calculated
                        checksum_file = archive_container_dir / f"{mtime_str}{self.MTIME_SEP}{size}{self.CHECKSUM_SUFFIX}"
                        logger.info(f':- {relative_p}  {mtime_str}  {checksum}')
                        checksum_file.write_text(checksum)
                    # file has changed as compared to the last backup
                    logger.info(f":= {relative_p}  {latest_mtime_str}  {latest_size} =: last backup")
                    self._create(CreateReason.CHANGED, p, relative_p, archive_container_dir, mtime_str, size)
        self._profile = None  # safeguard so that self.s will complain

    @staticmethod
    def should_ignore_for_archive(lstat: os.stat_result) -> bool:
        mode = lstat.st_mode
        return stat.S_ISSOCK(mode) or stat.S_ISDOOR(mode)

    @classmethod
    def get_checksum_file_path(cls, archive_path: Path) -> Path:
        core = cls.extract_core(archive_path.name)
        return archive_path.with_name(f"{core}{cls.CHECKSUM_SUFFIX}")

    @staticmethod
    def compute_checksum_of_file_in_archive(archive: Union[os.DirEntry, Path]) -> Optional[str]:
        with tarfile.open(archive) as tf:
            member = tf.getmembers()[0]
            return sha256(tf.extractfile(member).read()).hexdigest()

    def get_latest_archive(self, relative_p: str) -> Optional[Path]:
        archive_container_dir = self.compile_archive_container_dir(relative_p=relative_p)
        if not archive_container_dir.exists():
            return None
        latest_dir_entry = self.get_last_file_in_dir(archive_container_dir, self.RX_TAR)
        return Path(latest_dir_entry) if latest_dir_entry else None

    @classmethod
    def extract_mtime_size(cls, archive_path: Optional[Path]) -> Optional[tuple[str, int]]:
        if archive_path is None:
            return None
        core = cls.extract_core(archive_path.name)
        return cls.split_mtime_size(core)

    @classmethod
    def extract_core(cls, basename: str) -> str:
        """Example: 2023-04-30_09,48,20.872144+02,00~123#a7b6de.tar.gz => 2023-04-30_09,48,20+02,00~123#a7b6de"""
        try:
            core, _ = basename.rsplit(cls.DOT_TAR, 1)
        except ValueError:
            print(basename)
            raise
        return core

    @classmethod
    def split_ext(cls, basename: str) -> tuple[str, str]:
        """Example: 2023-04-30_09,48,20.872144+02,00~123.tar.gz => 2023-04-30_09,48,20+02,00~123 .gz"""
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

    @staticmethod
    def get_last_file_in_dir(archive_container_dir: Path, pattern: Pattern = None) -> Optional[os.DirEntry]:
        for dir_entry in sorted(os.scandir(archive_container_dir), key=lambda x: x.name, reverse=True):
            if dir_entry.is_file():
                if pattern is None:
                    return dir_entry
                elif pattern.search(dir_entry.name):
                    return dir_entry

    def _create(self, create_reason: CreateReason, path: Path, relative_p: str, archive_container_dir: Path, mtime_str: str, size: int):
        archive_container_dir.mkdir(parents=True, exist_ok=True)
        sign = create_reason.value
        logger.info(f"{sign} {relative_p}  {mtime_str}  {size} {sign} {archive_container_dir}")
        archive_format, compresslevel_kwargs = self.get_archive_format_and_compresslevel_kwargs(path)
        mode = self.ARCHIVE_FORMAT_TO_MODE[archive_format]
        is_lnk = stat.S_ISLNK(self.cached_lstat(path).st_mode)
        archive_path = self.make_archive_path(archive_container_dir, archive_format, mtime_str, size, self.LNK if is_lnk else self.BLANK)
        with tarfile.open(archive_path, mode, format=self.s.tar_format, **compresslevel_kwargs) as tf:
            tf.add(path, arcname=path.name)

    @classmethod
    def make_archive_path(cls, archive_container_dir: Path, archive_format: RumarFormat, mtime_str: str, size: int, comment: str = None) -> Path:
        return archive_container_dir / f"{mtime_str}{cls.MTIME_SEP}{size}{cls.MTIME_SEP + comment if comment else cls.BLANK}.{archive_format.value}"

    def compile_archive_container_dir(self, *, relative_p: Optional[str] = None, path: Optional[Path] = None) -> Path:
        assert relative_p or path, '** either relative_p or path must be provided'
        if not relative_p:
            relative_p = make_relative_p(path, self.s.source_dir)
        return self.s.backup_base_dir_for_profile / relative_p

    def get_archive_format_and_compresslevel_kwargs(self, path: Path) -> tuple[RumarFormat, dict]:
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
        for file_path in iter_matching_files(top_path, s):
            if s.skip_duplicate_files and (duplicate := self.find_duplicate(file_path)):
                logger.info(f"{make_relative_p(file_path, top_path)!r} -- skipping: duplicate of {make_relative_p(duplicate, top_path)!r}")
                continue
            yield file_path
        # sort by stem then suffix, i.e. 'abc.txt' before 'abc(2).txt'; ignore case
        matching_files.sort(key=lambda x: (x.stem.lower(), x.suffix.lower()))
        return matching_files

    def find_duplicate(self, file_path: Path) -> Optional[Path]:
        """
        If same suffix and same size and same part of name
        ignoring case (suffix, name)
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
        stems_and_paths = self._suffix_size_stems_and_paths.setdefault(suffix, {}).setdefault(size, {})
        stems_and_paths.setdefault(self.STEMS, []).append(stem)
        stems_and_paths.setdefault(self.PATHS, []).append(file_path)

    def extract_all(self, extract_root: Path):
        raise RuntimeError('not implemented')

    @staticmethod
    def _set_mtime(target_path: Path, mtime_dt: datetime):
        try:
            os.utime(target_path, (0, mtime_dt.timestamp()))
        except:
            logger.error(f">> error setting mtime -> {sys.exc_info()}")


class Broom:
    DASH = '-'

    def __init__(self, profile_to_settings: ProfileToSettings):
        self._profile_to_settings = profile_to_settings
        self._db = BroomDB()

    @classmethod
    def extract_date_from_name(cls, name: str) -> date:
        iso_date_string = name[:10]
        return date.fromisocalendar(*iso_date_string.split(cls.DASH))

    def sweep_all_profiles(self):
        for profile in self._profile_to_settings:
            self.sweep_profile(profile)

    def sweep_profile(self, profile, is_dry_run=False):
        logger.log(METHOD_17, f"{profile=}")
        s = self._profile_to_settings[profile]
        archive_format = RumarFormat(s.archive_format).value
        date_older_than_x_days = date.today() - timedelta(days=s.age_threshold_of_backups_to_sweep)
        for root, dirs, files in os.walk(s.backup_base_dir_for_profile):
            for file in files:
                path = Path(root, file)
                if self.is_archive(file, archive_format):
                    mdate = self.extract_date_from_name(file)
                    if mdate < date_older_than_x_days:
                        self._db.insert(path, mdate)
                else:
                    logger.warning(f":! {path.as_posix()}  is not an archive")
        self._db.update_counts(s)
        for dirname, basename, d, w, m, d_rm, w_rm, m_rm in self._db.iter_marked_for_removal():
            path = Path(dirname, basename)
            logger.info(f"-- {path.as_posix()}  is removed because it's #{d_rm} in {d}, #{w_rm} in week {w}, #{m_rm} in month {m}")
            if not is_dry_run:
                path.unlink()

    @staticmethod
    def is_archive(name: str, archive_format: str) -> bool:
        return (name.endswith(archive_format) or
                name.endswith(RumarFormat.TAR.value))


PeriodColType = Literal['d', 'w', 'm']
col_to_setting = {
    'd': 'number_of_daily_backups_to_keep',
    'w': 'number_of_weekly_backups_to_keep',
    'm': 'number_of_monthly_backups_to_keep',
}


class BroomDB:
    DATABASE = ':memory:'
    TABLE_PREFIX = 'broom_'
    TABLE_DT_FRMT = '%Y%m%d_%H%M%S'
    DATE_FORMAT = '%Y-%m-%d'
    WEEK_FORMAT = '%Y-%W'  # Monday as the first day of the week
    WEEK_ONLY_FORMAT = '%W'
    MONTH_FORMAT = '%Y-%m'
    DUNDER = '__'

    def __init__(self):
        self._db = sqlite3.connect(self.DATABASE)
        self._table = f"{self.TABLE_PREFIX}{datetime.now().strftime(self.TABLE_DT_FRMT)}"
        self.create_table()

    def create_table(self):
        ddl = dedent(f"""\
            CREATE TABLE {self._table} (
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

    def insert(self, path: Path, mdate: date):
        # logger.log(METHOD_17, f"{path.as_posix()}")
        params = (
            path.parent.as_posix(),
            path.name,
            mdate.strftime(self.DATE_FORMAT),
            self.compute_week(mdate),
            mdate.strftime(self.MONTH_FORMAT),
        )
        ins_stmt = f"INSERT INTO {self._table} (dirname, basename, d, w, m) VALUES (?,?,?,?,?)"
        self._db.execute(ins_stmt, params)
        self._db.commit()

    @classmethod
    def compute_week(cls, mdate: date) -> str:
        """
        consider week 0 as previous year's last week
        """
        if int(mdate.strftime(cls.WEEK_ONLY_FORMAT)) == 0:
            mdate = mdate.replace(day=1) - timedelta(days=1)
        return mdate.strftime(cls.WEEK_FORMAT)

    def update_counts(self, s: Settings):
        self._update_d_rm(s)
        self._update_w_rm(s)
        self._update_m_rm(s)

    def _update_d_rm(self, s: Settings):
        x = 'd'
        number_of_backups_to_keep = getattr(s, col_to_setting[x])
        stmt = dedent(f"""\
        SELECT b.dirname, b.{x}, b.id, agg.cnt, row_number() OVER win1 AS num
        FROM {self._table} b
        JOIN (
            SELECT dirname, {x}, count(*) cnt
            FROM {self._table} 
            GROUP BY dirname, {x}
            HAVING count(*) > {number_of_backups_to_keep}
        ) agg ON b.dirname = agg.dirname AND b.{x} = agg.{x}
        WINDOW win1 AS (PARTITION BY b.dirname, b.{x} ORDER BY b.dirname, b.{x}, b.id)
        ORDER BY b.dirname, b.{x}, b.id
        """)
        db = self._db
        cur = db.cursor()
        for row in db.execute(stmt):
            dirname, x_val, broom_id, x_cnt, x_num = row
            x_rm_target = x_cnt - number_of_backups_to_keep
            if x_rm_target > 0:
                if x_num <= x_rm_target:
                    updt_stmt = dedent(f"""\
                        UPDATE {self._table}
                        SET {x}_rm = '{x_num} of ({x_cnt} - {number_of_backups_to_keep})'
                        WHERE id = ?
                        """)
                    cur.execute(updt_stmt, (broom_id,))
        db.commit()

    def _update_w_rm(self, s: Settings):
        x = 'w'
        number_of_backups_to_keep = getattr(s, col_to_setting[x])
        stmt = dedent(f"""\
        SELECT b.dirname, b.{x}, b.id, agg.cnt, row_number() OVER win1 AS num
        FROM {self._table} b
        JOIN (
            SELECT dirname, {x}, count(*) cnt
            FROM {self._table} 
            GROUP BY dirname, {x}
            HAVING count(*) > {number_of_backups_to_keep}
        ) agg ON b.dirname = agg.dirname AND b.{x} = agg.{x}
        WHERE b.d_rm IS NOT NULL
        WINDOW win1 AS (PARTITION BY b.dirname, b.{x} ORDER BY b.dirname, b.{x}, b.id)
        ORDER BY b.dirname, b.{x}, b.id
        """)
        db = self._db
        cur = db.cursor()
        for row in db.execute(stmt):
            dirname, x_val, broom_id, x_cnt, x_num = row
            x_rm_target = x_cnt - number_of_backups_to_keep
            if x_rm_target > 0:
                if x_num <= x_rm_target:
                    updt_stmt = dedent(f"""\
                        UPDATE {self._table}
                        SET {x}_rm = '{x_num} of ({x_cnt} - {number_of_backups_to_keep})'
                        WHERE id = ?
                        """)
                    cur.execute(updt_stmt, (broom_id,))
        db.commit()

    def _update_m_rm(self, s: Settings):
        x = 'm'
        number_of_backups_to_keep = getattr(s, col_to_setting[x])
        stmt = dedent(f"""\
        SELECT b.dirname, b.{x}, b.id, agg.cnt, row_number() OVER win1 AS num
        FROM {self._table} b
        JOIN (
            SELECT dirname, {x}, count(*) cnt
            FROM {self._table} 
            GROUP BY dirname, {x}
            HAVING count(*) > {number_of_backups_to_keep}
        ) agg ON b.dirname = agg.dirname AND b.{x} = agg.{x}
        WHERE b.w_rm IS NOT NULL
        WINDOW win1 AS (PARTITION BY b.dirname, b.{x} ORDER BY b.dirname, b.{x}, b.id)
        ORDER BY b.dirname, b.{x}, b.id
        """)
        db = self._db
        cur = db.cursor()
        for row in db.execute(stmt):
            dirname, x_val, broom_id, x_cnt, x_num = row
            x_rm_target = x_cnt - number_of_backups_to_keep
            if x_rm_target > 0:
                if x_num <= x_rm_target:
                    updt_stmt = dedent(f"""\
                        UPDATE {self._table}
                        SET {x}_rm = '{x_num} of ({x_cnt} - {number_of_backups_to_keep})'
                        WHERE id = ?
                        """)
                    cur.execute(updt_stmt, (broom_id,))
        db.commit()

    def iter_marked_for_removal(self) -> Iterator[tuple[str, str, str, str, str, str, str, str]]:
        stmt = dedent(f"""\
            SELECT dirname, basename, d, w, m, d_rm, w_rm, m_rm
            FROM {self._table}
            WHERE m_rm IS NOT NULL
            """)
        for row in self._db.execute(stmt):
            yield row


if __name__ == '__main__':
    main()
