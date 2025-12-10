# Rumar

**A file-backup utility**

Files are backed up as **tar** archives, optionally compressed.

Each archive represents a version of the original file and is placed in a directory named as the original file,
in a mirrored directory tree.

Backups are created only if the original files have been changed,
i.e., their modification time and size (or checksum) differ from the last archive.

A single version can be restored from backup by extracting its respective archive using standard tools like Windows Explorer, Double Commander, or bsdtar.

**rumar extract** can restore a snapshot of an entire directory tree as of a particular point in time.

**rumar sweep** can remove old archives, keeping a specified number of file backups per month and/or week and/or day.

![](images/explorer.png)


![](images/terminal.png)

## How to use it

1. Install [Python](https://www.python.org/downloads/) (at least 3.10)
2. Download [rumar.py](https://raw.githubusercontent.com/macmarrum/rumar/main/src/rumar.py)
3. Download [rumar.toml](https://raw.githubusercontent.com/macmarrum/rumar/main/examples/rumar.toml) to the same directory as `rumar.py`
4. Edit `rumar.toml` and adapt it to your needs — see [settings details](#settings-details)
5. Open a console/terminal (e.g. PowerShell) and change to the directory containing `rumar.py`
6. If your installed Python version is below 3.11, run `python -m pip install tomli` to install the module [tomli](https://pypi.org/project/tomli/)
7. Run `python rumar.py list-profiles` — you should see your profile name(s) printed in the console
8. Run `python rumar.py create --profile "My Profile"` to execute a backup using the profile "My Profile"
9. Optionally, add the backup command to Task Scheduler or cron, to be run at an interval (e.g. each day/night)

See more options by running
- `python rumar.py create --help`

### How to restore a snapshot

1. Run `python rumar.py list-profiles --profile "My Profile" --runs` — to get **run_id** and **run_datetime_iso** for the profile "My Profile"
2. Run `python rumar.py extract --profile "My Profile" --run-id 123` to restore the backup as of the run_id 123 to the source directory

See more options by running
- `python rumar.py list-profiles --help`
- `python rumar.py extract --help`

### How to sweep old backups

1. Run `python rumar.py sweep --profile "My Profile" --dry-run` and verify the files to be removed
2. Run `python rumar.py sweep --profile "My Profile"` to remove old backups
3. Optionally, add the sweep command to Task Scheduler or cron, to be run at an interval (e.g. each day/night)

Note: when `--dry-run` is used, **rumar.py** counts the backup files and selects those to be removed based on settings, but no files are actually deleted.

See more options by running
- `python rumar.py sweep --help`

## Settings

Unless specified by `--toml path/to/your/settings.toml`,
settings are loaded from `rumar.toml` in the same directory as `rumar.py` or located in `rumar/rumar.toml` inside `$XDG_CONFIG_HOME` (`$HOME/.config` if not set) on POSIX,
or inside `%APPDATA%` on NT (Windows).

### Settings example

`rumar.toml`
<!-- rumar.toml example begin -->
```toml
# schema version
version = 2
# settings common for all profiles
backup_base_dir = 'C:\Users\Mac\Backup'

# setting for individual profiles - override any common ones

["My Documents"]
source_dir = 'C:\Users\Mac\Documents'
excluded_top_dirs = ['My Music', 'My Pictures', 'My Videos']
excluded_files_as_glob = ['desktop.ini', 'Thumbs.db']

[Desktop]
source_dir = 'C:\Users\Mac\Desktop'
excluded_files_as_glob = ['desktop.ini', '*.exe', '*.msi']

["# this profile's name starts with a hash, therefore it will be ignored"]
source_dir = "this setting won't be loaded"

[rumar-toml]
# profile to back up 'rumar.toml', e.g., with each `rumar.py c -a`
source_dir = '{rumar_config_dir}'
included_files_as_glob = ['rumar.toml', 'rumar.logging.toml']
checksum_comparison_if_same_size = true
db_path = ''

[rumar-sqlite]
# profile to back up 'rumar.sqlite', e.g., with each `rumar.py c -a`
source_dir = '{backup_base_dir}'
included_files_as_glob = ['rumar.sqlite']
checksum_comparison_if_same_size = true
archive_format = 'tar.xz'
compression_level = 4
db_path = ''
```
#### For Python >= 3.13
```toml
# schema version
version = 3
# settings common for all profiles
backup_base_dir = 'C:\Users\Mac\Backup'

# setting for individual profiles - override any common ones

["My Documents"]
source_dir = 'C:\Users\Mac\Documents'
excluded_files = ['My Music\**', 'My Pictures\**', 'My Videos\**', '**\desktop.ini', '**\Thumbs.db']

[Desktop]
source_dir = 'C:\Users\Mac\Desktop'
excluded_files = ['**\desktop.ini', '**\*.exe', '**\*.msi']

["# this profile's name starts with a hash, therefore it will be ignored"]
source_dir = "this setting won't be loaded"

[rumar-toml]
# profile to back up 'rumar.toml', e.g., with each `rumar.py c -a`
source_dir = '{rumar_config_dir}'
included_files = ['rumar.toml', 'rumar.logging.toml']
checksum_comparison_if_same_size = true
db_path = ''

[rumar-sqlite]
# profile to back up 'rumar.sqlite', e.g., with each `rumar.py c -a`
source_dir = '{backup_base_dir}'
included_files = ['rumar.sqlite']
checksum_comparison_if_same_size = true
archive_format = 'tar.xz'
compression_level = 4
db_path = ''
```
<!-- rumar.toml example end -->

### Settings details

Each profile whose name starts with a hash `#` is ignored when `rumar.toml` is loaded.\
**version** indicates the schema version – currently `3`.

<!-- settings pydoc begin -->
* **backup_base_dir**: str &nbsp; &nbsp; _Used by: create, sweep_\
  The path to the base directory used for backup; usually set in the global space, common for all profiles\
  ⓘ Note: The backup directory for each profile, i.e. _**backup_dir**_, is constructed as `{backup_base_dir}/{profile}`, unless _**backup_dir**_ is set, which takes precedence
* **backup_dir**: str = None &nbsp; &nbsp; _Used by: create, extract, sweep_\
  The path to the backup directory used for the profile\
  ⚠️ Caution: Usually left unset; if so, its value defaults to `{backup_base_dir}/{profile}`
* **archive_format**: Literal['tar', 'tar.gz', 'tar.bz2', 'tar.xz', 'tar.zst'] = 'tar.gz' &nbsp; &nbsp; _Used by: create, sweep_\
  The format of archive files to be created\
  ⚠️ Caution: 'tar.zst' requires Python 3.14+ or backports.zstd
* **compression_level**: int = 3 &nbsp; &nbsp; _Used by: create_\
  0 to 9 for 'tar.gz', 'tar.bz2', 'tar.xz'\
  0 to 22 for 'tar.zst'
* **no_compression_suffixes_default**: str = '7z,zip,zipx,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,cbz,png,jpg,gif,mp4,mov,avi,mp3,m4a,aac,ogg,ogv,opus,flac,kdbx' &nbsp; &nbsp; _Used by: create_\
  A comma-separated string of the default lower-case suffixes for which to use no compression
* **no_compression_suffixes**: str = '' &nbsp; &nbsp; _Used by: create_\
  A comma-separated string of extra lower-case suffixes in addition to _**no_compression_suffixes_default**_
* **tar_format**: Literal[0, 1, 2] = 1 (tarfile.GNU_FORMAT) &nbsp; &nbsp; _Used by: create_\
  See also https://docs.python.org/3/library/tarfile.html#supported-tar-formats and https://www.gnu.org/software/tar/manual/html_section/Formats.html
* **source_dir**: str &nbsp; &nbsp; _Used by: create, extract_\
  The path to the directory which is to be archived\
  ⓘ Note: `{rumar_config_dir}`, `{backup_base_dir}` can be used, which is useful in a profile to back up `rumar.toml` or `rumar.sqlite`
* **included_files**: list[str] &nbsp; &nbsp; _Used by: create, sweep_\
  ⚠️ Caution: Uses **PurePath.full_match(...)**, which is available on Python 3.13+\
  A list of glob patterns, also known as shell-style wildcards, i.e. `** * ? [seq] [!seq]`\
  ⓘ Note: `**` means zero or more segments, `*` means a single segment or a part of a segment (as in `My*`)\
  If present, only the matching files will be considered, together with _**included_files_as_regex**_, _**included_files_as_glob**_, _**included_top_dirs**_, _**included_dirs_as_regex**_\
  The paths/globs can be absolute or relative to _**source_dir**_ (or _**backup_dir**_ in case of _**sweep**_), e.g. `C:\My Documents\*.txt`, `my-file-in-source-dir.log`\
  Absolute paths start with a root (`/` or `{drive}:\`)\
  On Windows, global-pattern matching is case-insensitive, and both `\` and `/` can be used\
  See also https://docs.python.org/3.13/library/pathlib.html#pathlib-pattern-language
* **excluded_files**: list[str] &nbsp; &nbsp; _Used by: create, sweep_\
  ⚠️ Caution: Uses **PurePath.full_match(...)**, which is available on Python 3.13+\
  The matching files will be ignored, together with _**excluded_files_as_regex**_, _**excluded_files_as_glob**_, _**excluded_top_dirs**_, _**excluded_dirs_as_regex**_\
  See also _**included_files**_
* **included_top_dirs**: list[str] &nbsp; &nbsp; _Used by: create, sweep_\
  ❌ Deprecated: Use _**included_files**_ instead, if on Python 3.13+, e.g. `['top dir 1/**',]`\
  A list of top-directory paths\
  If present, only the files from the directories and their descendant subdirs will be considered, together with _**included_dirs_as_regex**_, _**included_files**_, _**included_files_as_regex**_, _**included_files_as_glob**_\
  The paths can be relative to _**source_dir**_ or absolute, but always under _**source_dir**_ (or _**backup_dir**_ in case of _**sweep**_)\
  Absolute paths start with a root (`/` or `{drive}:\`)
* **excluded_top_dirs**: list[str] &nbsp; &nbsp; _Used by: create, sweep_\
  ❌ Deprecated: Use _**excluded_files**_ instead, if on Python 3.13+, e.g. `['top dir 3/**',]`\
  The files from the directories and their subdirs will be ignored, together with _**excluded_dirs_as_regex**_, _**excluded_files**_, _**excluded_files_as_regex**_, _**excluded_files_as_glob**_\
  See also _**included_top_dirs**_
* **included_dirs_as_regex**: list[str] &nbsp; &nbsp; _Used by: create, sweep_\
  A list of regex patterns (each to be passed to re.compile)\
  If present, only the file from the matching directories will be considered, together with _**included_top_dirs**_, _**included_files**_, _**included_files_as_regex**_, _**included_files_as_glob**_\
  `/` must be used as the path separator, also on Windows\
  The patterns are matched (using re.search) against a path relative to _**source_dir**_ (or _**backup_dir**_ in case of _**sweep**_)\
  The first segment in the relative path to match against also starts with a slash,\
  e.g., `['/B$',]` will match each directory named `B`, at any level; `['^/B$',]` will match only `{source_dir}/B` (or `{backup_dir}/B` in case of _**sweep**_)\
  Regex-pattern matching is case-sensitive – use `(?i)` at each pattern's beginning for case-insensitive matching, e.g. `['(?i)/b$',]`\
  See also https://docs.python.org/3/library/re.html
* **excluded_dirs_as_regex**: list[str] &nbsp; &nbsp; _Used by: create, sweep_\
  The files from the matching directories will be ignored, together with _**excluded_top_dirs**_, _**excluded_files**_, _**excluded_files_as_regex**_, _**excluded_files_as_glob**_\
  See also _**included_dirs_as_regex**_
* **included_files_as_glob**: list[str] &nbsp; &nbsp; _Used by: create, sweep_\
  ❌ Deprecated: Use _**included_files**_ instead, if on Python 3.13+\
  A list of glob patterns, also known as shell-style wildcards, i.e. `* ? [seq] [!seq]`\
  If present, only the matching files will be considered, together with _**included_files**_, _**included_files_as_regex**_, _**included_top_dirs**_, _**included_dirs_as_regex**_,\
  and only if its parent directory is also included, e.g., by one of the *\_dirs filters\
  The paths/globs can be partial, relative to _**source_dir**_ or absolute, but always under _**source_dir**_ (or _**backup_dir**_ in case of _**sweep**_)\
  Unlike with glob patterns used in _**included_files**_, here matching is done from the right if the pattern is relative, e.g. `['B\b1.txt',]` will match `C:\A\B\b1.txt` and `C:\B\b1.txt`\
  ⚠️ Caution: A leading path separator indicates an absolute path, but on Windows you also need a drive letter, e.g., `['\A\a1.txt']` will never match; use `['C:\A\a1.txt']` instead\
  On Windows, global-pattern matching is case-insensitive, and both `\` and `/` can be used\
  See also https://docs.python.org/3/library/fnmatch.html and https://en.wikipedia.org/wiki/Glob_(programming)
* **excluded_files_as_glob**: list[str] &nbsp; &nbsp; _Used by: create, sweep_\
  ❌ Deprecated: use _**excluded_files**_ instead, if on Python 3.13+\
  The matching files will be ignored, together with _**excluded_files**_, _**excluded_files_as_regex**_, _**excluded_top_dirs**_, _**excluded_dirs_as_regex**_\
  See also _**included_files_as_glob**_
* **included_files_as_regex**: list[str] &nbsp; &nbsp; _Used by: create, sweep_\
  If present, only the matching files will be considered, together with _**included_files**_, _**included_files_as_glob**_, _**included_top_dirs**_, _**included_dirs_as_regex**_,\
  and only if its parent directory is also included, e.g., by one of the *\_dirs filters\
  See also _**included_dirs_as_regex**_
* **excluded_files_as_regex**: list[str] &nbsp; &nbsp; _Used by: create, sweep_\
  The matching files will be ignored, together with _**excluded_files**_, _**excluded_files_as_glob**_, _**excluded_top_dirs**_, _**excluded_dirs_as_regex**_\
  See also _**included_dirs_as_regex**_
* **checksum_comparison_if_same_size**: bool = False &nbsp; &nbsp; _Used by: create_\
  When False, a file is considered changed if its mtime is different than the latest backup's mtime and its size has changed\
  When True, BLAKE2b checksum is calculated to determine if the file changed despite having the same size\
  ⓘ Note: mtime := last modification time\
  See also https://en.wikipedia.org/wiki/File_verification
* **file_deduplication**: bool = False &nbsp; &nbsp; _Used by: create_\
  When True, an attempt is made to find and skip duplicates\
  A duplicate file has the same suffix and size and part of its name, case-insensitive (suffix, name)
* **min_age_in_days_of_backups_to_sweep**: int = 2 &nbsp; &nbsp; _Used by: sweep_\
  Only the backups which are older than the specified number of days are considered for removal
* **number_of_backups_per_day_to_keep**: int = 2 &nbsp; &nbsp; _Used by: sweep_\
  For each file, the specified number of backups per day is kept, if available\
  More backups per day might be kept to satisfy _**number_of_backups_per_week_to_keep**_ and/or _**number_of_backups_per_month_to_keep**_\
  Oldest backups are removed first
* **number_of_backups_per_week_to_keep**: int = 14 &nbsp; &nbsp; _Used by: sweep_\
  For each file, the specified number of backups per week is kept, if available\
  More backups per week might be kept to satisfy _**number_of_backups_per_day_to_keep**_ and/or _**number_of_backups_per_month_to_keep**_\
  Oldest backups are removed first
* **number_of_backups_per_month_to_keep**: int = 60 &nbsp; &nbsp; _Used by: sweep_\
  For each file, the specified number of backups per month is kept, if available\
  More backups per month might be kept to satisfy _**number_of_backups_per_day_to_keep**_ and/or _**number_of_backups_per_week_to_keep**_\
  Oldest backups are removed first
* **commands_using_filters**: list[str] = ['create'] &nbsp; &nbsp; _Used by: create, sweep_\
  Determines which commands can use the filters specified in the included_* and excluded_* settings\
  By default, filters are used only by _**create**_, i.e. _**sweep**_ considers all created backups (no filter is applied)\
  A filter for _**sweep**_ could be used to e.g. never remove backups from the first day of a month:\
  `excluded_files = ['**/[0-9][0-9][0-9][0-9]-[0-9][0-9]-01_*.tar*']` or\
  `excluded_files_as_regex = ['/\d\d\d\d-\d\d-01_\d\d,\d\d,\d\d(\.\d{6})?[+-]\d\d,\d\d~\d+(~.+)?\.tar(\.(gz|bz2|xz|zst))?$']`\
  It's best when the setting is part of a separate profile, i.e. a copy made for _**sweep**_,\
  otherwise _**create**_ will also seek such files to be excluded
* **db_path**: str = None &nbsp; &nbsp; _Used by: create, extract, reconcile_\
  The path to the rumar database file — used for tracking changes, e.g., deletion of source files, to avoid restoring deleted ones with _**extract**_\
  ⚠️ Caution: Usually left unset; if so, its value defaults to `{backup_base_dir}/rumar.sqlite`\
  The following settings can be used in _**db_path**_: `{profile}`, `{backup_base_dir}`, `{backup_dir}`, `{source_dir}`, `{rumar_config_dir}`\
  An empty string (`''`) disables the database
<!-- settings pydoc end -->

### Settings schema version 3 vs 2

Version 3 has the additional settings _**included_files**_ and _**excluded_files**_.
They rely on `PurePath.full_match(...)`, which was added in Python 3.13.\
The new settings remove the need for the following ones:
* _**included_top_dirs**_
* _**excluded_top_dirs**_
* _**included_files_as_glob**_
* _**excluded_files_as_glob**_

Also _**backup_base_dir_for_profile**_ is renamed to _**backup_dir**_.

### Settings schema version 2 vs 1

Version 1 contained _**sha256_comparison_if_same_size**_.\
In version 2 it's _**checksum_comparison_if_same_size**_.

## Logging settings

If `--toml` is used, logging settings are loaded from `rumar.logging.toml` if it exists next to the file pointed to by `--toml`.
Otherwise, logging settings are loaded from the default location or an internal `LOGGING_TOML_DEFAULT`.
The default location is `rumar/rumar.logging.toml` inside `$XDG_CONFIG_HOME` (`$HOME/.config` if not set) on POSIX,
or inside `%APPDATA%` on NT (Windows).
You can copy the below settings to your own file and modify them as needed.

By default, `rumar.log` is created in the current directory (where `rumar.py` is executed).
This can be changed by setting `filename=/path/to/rumar.log`.\
To disable the creation of `rumar.log`,
put a hash `#` in front of `"to_file",` in `[loggers.rumar]`.

<!-- logging settings begin -->
```toml
version = 1
func_name_width_with_padding = 25

[formatters.f1]
format = "{levelShort} {asctime} {funcName}:{funcNamePadding} {message}"
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
level = "INFO"
```
<!-- logging settings end -->
More information: <https://docs.python.org/3/library/logging.config.html#logging-config-dictschema>

---
Copyright © 2023-2025 [macmarrum](https://github.com/macmarrum)\
SPDX-License-Identifier: [GPL-3.0-or-later](/LICENSE)
