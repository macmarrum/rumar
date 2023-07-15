# Rumar

**A backup utility**

Creates a directory named as the original file, containing a **tar**red copy of the file, optionally compressed.

Files are added to the **tar** archive only if they were changed, as compared to the last archive.

\
The directory containing **tar** files is placed in a mirrored directory hierarchy.

![](images/original-and-backup-directories.png)

\
Each backup is a separate **tar** file.

![](images/original-file-and-tar-containing-directory.png)

## How to use it

1. Install [Python](https://www.python.org/downloads/) (at least 3.9), if not yet installed
2. Download [rumar.py](https://raw.githubusercontent.com/macmarrum/rumar/main/src/rumar.py)
3. Create your `rumar.toml` settings in the same directory as `rumar.py` – see [settings example](#settings-example)
4. Open terminal in the directory containing `rumar.py`
5. If your installed Python version is below 3.11, run `python -m pip install tomli` to install the module [tomli](https://pypi.org/project/tomli/), if not yet installed
6. Run `python rumar.py list-profiles`; you should see your profile name printed in the console
7. Run `python rumar.py create --profile "My Documents"` to create a backup of the profile "My Documents"
8. Add this command to Task Scheduler or cron, to be run at an interval or each day/night

### To sweep old backups

1. Run `python rumar.py sweep --profile "My Documents" --dry-run` and verify the files to be removed
2. Run `python rumar.py sweep --profile "My Documents"`
3. Add this command to Task Scheduler or cron, to be run at an interval or each day/night

Note: when --dry-run is used, file selection is run to count and select files to be removed but no files are actually deleted.

## Settings

Unless specified by `--toml path/to/your/settings.toml`,
settings are read from `rumar.toml` in the same directory as `rumar.py` or located in `rumar/rumar.toml` inside `$XDG_CONFIG_HOME` (`$HOME/.config` if not set) on POSIX,
or inside `%APPDATA%` on NT (Windows).

### Settings example

```toml
# rumar.toml
backup_base_dir = 'c:\Users\Mac\Backup'

["My Documents"]
source_dir = 'c:\Users\Mac\Documents'
excluded_dirs_as_glob = ['/My Music', '/My Pictures', '/My Videos']
excluded_files_as_regex = ['/(desktop\.ini|thumbs\.db)$']
```

### Settings details

<!-- settings pydoc begin -->
* **backup_base_dir**: str &nbsp; &nbsp; _used by: create, sweep_\
  path to the base directory used for backup; usually set in the global space, common for all profiles\
  backup dir for each profile is constructed as backup_base_dir + profile, unless backup_base_dir_for_profile is set, which takes precedence
* **backup_base_dir_for_profile**: str &nbsp; &nbsp; _used by: create, sweep_\
  path to the base dir used for the profile; usually left unset; see backup_base_dir
* **archive_format**: Literal['tar', 'tar.gz', 'tar.bz2', 'tar.xz'] = 'tar.gz' &nbsp; &nbsp; _used by: create, sweep_\
  archive file to be created
* **compression_level**: int = 3 &nbsp; &nbsp; _used by: create_\
  for the formats 'tar.gz', 'tar.bz2', 'tar.xz': compression level from 0 to 9
* **no_compression_suffixes_default**: str = '7z,zip,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,png,jpg,gif,mp4,mov,avi,mp3,m4a,aac,ogg,ogv,kdbx' &nbsp; &nbsp; _used by: create_\
  comma-separated string of lower-case suffixes for which to use uncompressed tar
* **no_compression_suffixes**: str = '' &nbsp; &nbsp; _used by: create_\
  extra lower-case suffixes in addition to no_compression_suffixes_default
* **tar_format**: Literal[0, 1, 2] = tarfile.GNU_FORMAT &nbsp; &nbsp; _used by: create_\
  Double Commander fails to correctly display mtime when PAX is used, therefore GNU is the default
* **source_dir**: str &nbsp; &nbsp; _used by: create_\
  path to the directory which is to be archived
* **included_dirs_as_glob**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  a list of glob patterns, also known as shell-style wildcards, i.e. `* ? [seq] [!seq]`\
  if present, only matching directories will be considered\
  the paths/globs can be absolute or partial paths, but always under source_dir\
  see also https://docs.python.org/3/library/fnmatch.html and https://en.wikipedia.org/wiki/Glob_(programming)
* **included_files_as_glob**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  like included_dirs_as_glob, but for files
* **excluded_dirs_as_glob**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  like included_dirs_as_glob, but to exclude
* **excluded_files_as_glob**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  like included_files_as_glob, but to exclude
* **included_dirs_as_regex**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  a list of regex patterns\
  if present, only matching directories will be included\
  `/` must be used as the path separator, also on Windows\
  the patterns are matched against a path relative to source_dir\
  the first segment in the relative path (to match against) also starts with a slash\
  e.g. `['/B$',]` will match any basename equal to `B`, at any level\
  see also https://docs.python.org/3/library/re.html
* **included_files_as_regex**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  like included_dirs_as_regex but for files
* **excluded_dirs_as_regex**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  like included_dirs_as_regex, but for exclusion
* **excluded_files_as_regex**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  like included_files_as_regex, but for exclusion
* **sha256_comparison_if_same_size**: bool = False &nbsp; &nbsp; _used by: create_\
  when False, a file is considered changed if its mtime is later than the latest backup's mtime and its size changed\
  when True, SHA256 checksum is compared to determine if the file changed despite having the same size
* **file_deduplication**: bool = False &nbsp; &nbsp; _used by: create_\
  when True, an attempt is made to find and skip duplicates\
  a duplicate file has the same suffix and size and part of its name, case-insensitive (suffix, name)
* **age_threshold_of_backups_to_sweep**: int = 2 &nbsp; &nbsp; _used by: sweep_\
  only the backups which are older than the specified number of days are considered for removal
* **number_of_backups_per_day_to_keep**: int = 2 &nbsp; &nbsp; _used by: sweep_\
  for each file, the specified number of backups per day is kept, if available, or more, to make weekly and/or monthly numbers\
  oldest backups are removed first
* **number_of_backups_per_week_to_keep**: int = 14 &nbsp; &nbsp; _used by: sweep_\
  for each file, the specified number of backups per week is kept, if available, or more, to make monthly numbers\
  oldest backups are removed first
* **number_of_backups_per_month_to_keep**: int = 60 &nbsp; &nbsp; _used by: sweep_\
  for each file, the specified number of backups per month is kept, if available\
  oldest backups are removed first
* **filter_usage**: Literal[1, 2, 3] = 1 &nbsp; &nbsp; _used by: create, sweep_\
  determines which command can use the included_* and excluded_* settings\
  1: create\
  2: sweep\
  3: create and sweep\
  by default only used by create, i.e. sweep considers all created backups (no filter is applied)\
  a filter for sweep could be used to e.g. never remove backups from the first day of a month:\
  `excluded_files_as_regex = '/\d\d\d\d-\d\d-01_\d\d,\d\d,\d\d(+|-)\d\d,\d\d\.tar(\.(gz|bz2|xz))?$'`\
  it's best when the setting is part of a separate profile, i.e. a copy made for sweep,\
  otherwise create will also seek such files to be excluded
<!-- settings pydoc end -->