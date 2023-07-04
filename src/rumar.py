#!/usr/bin/python3
import argparse
import logging
import os
import re
import stat
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from typing import Iterator, Union, Optional, Literal, TypeVar, Pattern, Any

import tomli

vi = sys.version_info
assert (vi.major, vi.minor) >= (3, 9), 'expected Python 3.9 or higher'

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


Options = TypeVar('Options')  # so that mypy does not complain for from_toml_dict -> Options
create_args = ('-c', '--create')
extract_args = ('-x', '--extract')


def main():
    store_true = 'store_true'
    parser = argparse.ArgumentParser()
    action_gr = parser.add_mutually_exclusive_group(required=True)
    action_gr.add_argument(*create_args, action=store_true)
    action_gr.add_argument(*extract_args, action=store_true)
    action_gr.add_argument('-l', '--list-profiles', action=store_true)
    parser.add_argument('-e', '--extract-root', type=make_path, required=is_extract())
    parser.add_argument('-t', '--toml', type=make_path, default=get_default_path(suffix='.toml'))
    profile_gr = parser.add_mutually_exclusive_group(required=is_create() or is_extract())
    profile_gr.add_argument('-a', '--all', action=store_true)
    profile_gr.add_argument('-p', '--profile')
    args = parser.parse_args()
    profile_to_options = create_profile2options_from_toml(args.toml)
    rumar = Rumar(profile_to_options)
    if args.all:
        rumar.create_for_all_profiles()
    elif args.list_profiles:
        print('Profiles:')
        for profile, options in profile_to_options.items():
            print(f" {options}")
    else:
        rumar.create_for_profile(args.profile)


def is_extract():
    for a in sys.argv:
        if a in extract_args:
            return True
    return False


def is_create():
    for a in sys.argv:
        if a in create_args:
            return True
    return False


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


class RumarFormat(Enum):
    TAR = 'tar'
    TGZ = 'tar.gz'
    TBZ = 'tar.bz2'
    TXZ = 'tar.xz'


@dataclass
class Options:
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
    no_compression_suffixes_default: str = '7z,zip,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,png,jpg,mp4,mov,,mp3,m4a,acc,ogg,ogv,kdbx'
        comma-separated string of lower-case suffixes for which to use uncompressed tar
    no_compression_suffixes: str = ''
        extra lower-case suffixes in addition to no_compression_suffixes_default
    tar_format: Literal[0, 1, 2] = tarfile.GNU_FORMAT
      DoubleCmd fails to correctly display mtime when PAX is used -- GNU is recommended
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
    """
    profile: str
    backup_base_dir: Union[str, Path]
    source_dir: Union[str, Path]
    backup_base_dir_for_profile: Optional[Union[str, Path]] = None
    source_files: Optional[Union[list[str], list[Path]]] = None
    excluded_dirs_as_regex: Optional[Union[list[str], list[Pattern]]] = None
    excluded_files_as_regex: Optional[Union[list[str], list[Pattern]]] = None
    archive_format: Union[str, RumarFormat] = RumarFormat.TGZ
    compression_level: int = 3
    no_compression_suffixes_default: str = (
        '7z,zip,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,'
        'xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,'
        'png,jpg,mp4,mov,mp3,m4a,acc,ogg,ogv,'
    )
    no_compression_suffixes: str = ''
    tar_format: Literal[0, 1, 2] = tarfile.GNU_FORMAT
    sha256_comparison_if_same_size: bool = False
    skip_duplicate_files: bool = False
    COMMA = ','

    @staticmethod
    def is_each_elem_of_type(lst: list, typ: Union[Any, tuple]) -> bool:
        return all(isinstance(elem, typ) for elem in lst)

    def __post_init__(self):
        if not isinstance(self.backup_base_dir, Path):
            self.backup_base_dir = Path(self.backup_base_dir)
        if self.backup_base_dir_for_profile:
            if not isinstance(self.backup_base_dir_for_profile, Path):
                self.backup_base_dir_for_profile = Path(self.backup_base_dir_for_profile)
        else:
            self.backup_base_dir_for_profile = self.backup_base_dir / self.profile
        if not isinstance(self.source_dir, Path):
            self.source_dir = Path(self.source_dir)
        if self.source_files and not self.is_each_elem_of_type(self.source_files, Path):
            self.source_files = [Path(elem) for elem in self.source_files]
        if self.excluded_files_as_regex and not self.is_each_elem_of_type(self.excluded_files_as_regex, re.Pattern):
            self.excluded_files_as_regex = [re.compile(elem) for elem in self.excluded_files_as_regex]
        if self.excluded_dirs_as_regex and not self.is_each_elem_of_type(self.excluded_dirs_as_regex, re.Pattern):
            self.excluded_dirs_as_regex = [re.compile(elem) for elem in self.excluded_dirs_as_regex]
        self.suffixes_without_compression = {f".{s}" for s in self.COMMA.join([self.no_compression_suffixes_default, self.no_compression_suffixes]).split(self.COMMA) if s}
        # https://stackoverflow.com/questions/71846054/-cast-a-string-to-an-enum-during-instantiation-of-a-dataclass-
        if self.archive_format is None:
            self.archive_format = RumarFormat.TGZ
        self.archive_format = RumarFormat(self.archive_format)

    def __str__(self):
        source_files = f", source_files: {[f.as_posix() if isinstance(f, Path) else f for f in self.source_files]!r}" if self.source_files else ''
        return ("{"
                f"profile: {self.profile!r}, "
                f"backup_base_dir_for_profile: {self.backup_base_dir_for_profile.as_posix()!r}, "
                f"source_dir: {self.source_dir.as_posix()!r}"
                f"{source_files}"
                "}")


ProfileToOptions = dict[str, Options]


def create_profile2options_from_toml(toml_file: Path) -> ProfileToOptions:
    logger.log(DEBUG_11, f"{toml_file=}")
    profile_to_options: ProfileToOptions = {}
    toml_str = toml_file.read_text(encoding='UTF-8')
    toml_dict = tomli.loads(toml_str)
    common_kwargs_for_options = {}
    profile_to_dict = {}
    for key, value in toml_dict.items():
        if isinstance(value, dict):
            profile_to_dict[key] = value
        else:
            common_kwargs_for_options[key] = value
    for profile, dct in profile_to_dict.items():
        kwargs_for_options = common_kwargs_for_options.copy()
        kwargs_for_options['profile'] = profile
        for key, value in dct.items():
            kwargs_for_options[key] = value
        profile_to_options[profile] = Options(**kwargs_for_options)
    return profile_to_options


class CreateReason(Enum):
    NEW = '+>'
    CHANGED = '~>'


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

    def __init__(self, profile_to_options: ProfileToOptions):
        self._profile_to_options = profile_to_options
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

    def create_for_profile(self, profile: str):
        """Create a backup for the specified profile
        """
        assert profile in self._profile_to_options
        self._profile = profile
        for p in self.source_files:
            relative_p = self._make_relative(p)
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
                        if self.o.sha256_comparison_if_same_size:
                            checksum_file = self.get_checksum_file(latest_archive)
                            if not checksum_file.exists():
                                latest_checksum = self.get_checksum_from_archive(latest_archive)
                                logger.info(f':- {relative_p}  {latest_mtime_str}  {latest_checksum}')
                                checksum_file.write_text(latest_checksum)
                            else:
                                latest_checksum = checksum_file.read_text()
                            checksum = sha256(p.open('rb').read()).hexdigest()
                            is_changed = checksum != latest_checksum
                if is_changed:
                    if checksum:  # save checksum, if it was calculated
                        checksum_file = archive_container_dir / f"{mtime_str}{self.MTIME_SEP}{size}{self.CHECKSUM_SUFFIX}"
                        logger.info(f':- {relative_p}  {mtime_str}  {checksum}')
                        checksum_file.write_text(checksum)
                    # file has changed as compared to the last backup
                    logger.info(f":= {relative_p}  {latest_mtime_str}  {latest_size} =: last backup")
                    self._create(CreateReason.CHANGED, p, relative_p, archive_container_dir, mtime_str, size)
        self._profile = None

    def create_for_all_profiles(self):
        for profile in self._profile_to_options:
            self.create_for_profile(profile)

    def _make_relative(self, path: Path) -> str:
        return path.as_posix().removeprefix(self.o.source_dir.as_posix()).removeprefix('/')

    @staticmethod
    def should_ignore_for_archive(lstat: os.stat_result) -> bool:
        mode = lstat.st_mode
        return stat.S_ISSOCK(mode) or stat.S_ISDOOR(mode)

    @classmethod
    def get_checksum_file(cls, archive_path: Path) -> Path:
        core = cls.extract_core(archive_path.name)
        return archive_path.with_name(f"{core}{cls.CHECKSUM_SUFFIX}")

    @staticmethod
    def get_checksum_from_archive(archive: Union[os.DirEntry, Path]) -> Optional[str]:
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
        with tarfile.open(archive_path, mode, format=self.o.tar_format, **compresslevel_kwargs) as tf:
            tf.add(path, arcname=path.name)

    @classmethod
    def make_archive_path(cls, archive_container_dir: Path, archive_format: RumarFormat, mtime_str: str, size: int, comment: str = None) -> Path:
        return archive_container_dir / f"{mtime_str}{cls.MTIME_SEP}{size}{cls.MTIME_SEP + comment if comment else cls.BLANK}.{archive_format.value}"

    def compile_archive_container_dir(self, *, relative_p: Optional[str] = None, path: Optional[Path] = None) -> Path:
        assert relative_p or path, '** either relative_p or path must be provided'
        if not relative_p:
            relative_p = self._make_relative(path)
        return self.o.backup_base_dir_for_profile / relative_p

    def get_archive_format_and_compresslevel_kwargs(self, path: Path) -> tuple[RumarFormat, dict]:
        if (
                path.is_absolute() and  # for gardner.repack, which has only arc_name
                stat.S_ISLNK(self.cached_lstat(path).st_mode)
        ):
            return self.SYMLINK_FORMAT_COMPRESSLEVEL
        elif path.suffix.lower() in self.o.suffixes_without_compression or self.o.archive_format == RumarFormat.TAR:
            return self.NOCOMPRESSION_FORMAT_COMPRESSLEVEL
        else:
            key = self.PRESET if self.o.archive_format == RumarFormat.TXZ else self.COMPRESSLEVEL
            return self.o.archive_format, {key: self.o.compression_level}

    @property
    def o(self) -> Options:
        return self._profile_to_options[self._profile]

    @property
    def source_files(self) -> Iterator[Path]:
        """if source_files are present, use those
        otherwise walk the source_dir
        """
        if self.o.source_files:
            for file_path in self.o.source_files:
                yield self.o.source_dir / self._make_relative(Path(file_path))
        else:
            for p in self._walk(self.o.source_dir):
                yield p

    def _walk(self, root: Path) -> Iterator[Path]:
        """
        iterator of files to be backed up
        any logic to exclude some files goes here
        """
        files = []
        directories = []
        for basename in os.listdir(root):
            dir_path = root / basename
            mode = self.cached_lstat(dir_path).st_mode
            is_dir = stat.S_ISDIR(mode)
            if is_dir:
                excluded_relative_p, rx = self._get_relative_if_excluded(dir_path, self.o.excluded_dirs_as_regex)
            else:
                excluded_relative_p, rx = self._get_relative_if_excluded(dir_path, self.o.excluded_files_as_regex)
            if excluded_relative_p:
                logger.info(f"|| ...{excluded_relative_p}  -- skipping: matches '{rx}'")
                continue
            if is_dir and not stat.S_ISLNK(mode):
                directories.append(dir_path)
            else:
                files.append(dir_path)
        # yield files first, only then recurse into sub-dirs; sort by stem then suffix, i.e. 'abc.txt' before 'abc(2).txt'
        for file_path in sorted(files, key=lambda x: (x.stem.lower(), x.suffix.lower())):
            if self.o.skip_duplicate_files and (duplicate := self.find_duplicate(file_path)):
                logger.info(f"{self._make_relative(file_path)!r} -- skipping: duplicate of {self._make_relative(duplicate)!r}")
                continue
            yield file_path
        for dir_path in sorted(directories, key=lambda x: x.name.lower()):
            for file_path in self._walk(dir_path):
                yield file_path

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

    def _get_relative_if_excluded(self, path: Path, excluded: list[Pattern]) -> tuple[str, Pattern]:
        if excluded:
            # make sure the first segment in the relative path (to match against) also starts with a slash
            relative_p = self.SLASH + self._make_relative(path)
            for rx in excluded:
                if rx.search(relative_p):
                    return relative_p, rx.pattern
        return self.BLANK, self.RX_NONE

    def extract_all(self, extract_root: Path):
        raise RuntimeError('not implemented')

    @staticmethod
    def _set_mtime(target_path: Path, mtime_dt: datetime):
        try:
            os.utime(target_path, (0, mtime_dt.timestamp()))
        except:
            logger.error(f">> error setting mtime -> {sys.exc_info()}")


if __name__ == '__main__':
    main()
