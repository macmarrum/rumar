# Rumar

**A file-backup utility**

Creates a directory named as the original file, containing a **tar**red copy of the file, optionally compressed.

Files are added to the **tar** archive only if they were changed, as compared to the last archive.

The directory containing **tar** files is placed in a mirrored directory hierarchy.

![](images/original-and-backup-directories.png)

\
Each backup is a separate **tar** file.

![](images/original-file-and-tar-containing-directory.png)

## How to use it

1. Install [Python](https://www.python.org/downloads/) (at least 3.9), if not yet installed
2. Download [rumar.py](https://raw.githubusercontent.com/macmarrum/rumar/main/src/rumar.py)
3. Download [rumar.toml](https://raw.githubusercontent.com/macmarrum/rumar/main/examples/rumar.toml) to the same directory as `rumar.py`
4. Edit `rumar.toml` and adapt it to your needs – see [settings details](#settings-details)
5. Open a console/terminal (e.g. Windows PowerShell) and change to the directory containing `rumar.py`
6. If your installed Python version is below 3.11, run `python -m pip install tomli` to install the module [tomli](https://pypi.org/project/tomli/), if not yet done
7. Run `python rumar.py list-profiles` → you should see your profile name(s) printed in the console
8. Run `python rumar.py create --profile "My Documents"` to create a backup using the profile "My Documents"
9. Add this command to Task Scheduler or cron, to be run at an interval or each day/night

### How to sweep old backups

1. Run `python rumar.py sweep --profile "My Documents" --dry-run` and verify the files to be removed
2. Run `python rumar.py sweep --profile "My Documents"` to remove old backups
3. Add this command to Task Scheduler or cron, to be run at an interval or each day/night

Note: when `--dry-run` is used, **rumar.py** counts the backup files and selects those to be removed based on settings, but no files are actually deleted.

## Settings

Unless specified by `--toml path/to/your/settings.toml`,
settings are loaded from `rumar.toml` in the same directory as `rumar.py` or located in `rumar/rumar.toml` inside `$XDG_CONFIG_HOME` (`$HOME/.config` if not set) on POSIX,
or inside `%APPDATA%` on NT (MS Windows).

### Settings example

`rumar.toml`
<!-- rumar.toml example begin -->
```toml
# schema version - always 1
version = 1
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

['# this profile starts with a hash, therefore will be ignored']
source_dir = "this setting won't be loaded"
```
<!-- rumar.toml example end -->

### Settings details

Profiles which start with a hash `#` are ignored when `rumar.toml` is loaded.\
**version** indicates schema version and for now is always `1`.

<!-- settings pydoc begin -->
* **backup_base_dir**: str &nbsp; &nbsp; _used by: create, sweep_\
  path to the base directory used for backup; usually set in the global space, common for all profiles\
  backup dir for each profile is constructed as _**backup_base_dir**_ + _**profile**_, unless _**backup_base_dir_for_profile**_ is set, which takes precedence
* **backup_base_dir_for_profile**: str &nbsp; &nbsp; _used by: create, sweep_\
  path to the base dir used for the profile; usually left unset; see _**backup_base_dir**_
* **archive_format**: Literal['tar', 'tar.gz', 'tar.bz2', 'tar.xz', 'zipx'] = 'tar.gz' &nbsp; &nbsp; _used by: create, sweep_\
  format of archive files to be created\
  zipx is AES-encrypted, therefore password must be provided
* **password**: str &nbsp; &nbsp; _used by: create_\
  for zipx encryption
* **compression_level**: int = 3 &nbsp; &nbsp; _used by: create_\
  for the formats 'tar.gz', 'tar.bz2', 'tar.xz', 'zipx': compression level from 0 to 9
* **no_compression_suffixes_default**: str = '7z,zip,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,png,jpg,gif,mp4,mov,avi,mp3,m4a,aac,ogg,ogv,kdbx' &nbsp; &nbsp; _used by: create_\
  for the formats 'tar.gz', 'tar.bz2', 'tar.xz': compression level from 0 to 9
* **no_compression_suffixes_default**: str = '7z,zip,zipx,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,png,jpg,gif,mp4,mov,avi,mp3,m4a,aac,ogg,ogv,kdbx' &nbsp; &nbsp; _used by: create_\
  comma-separated string of lower-case suffixes for which to use uncompressed tar
* **no_compression_suffixes**: str = '' &nbsp; &nbsp; _used by: create_\
  extra lower-case suffixes in addition to _**no_compression_suffixes_default**_
* **tar_format**: Literal[0, 1, 2] = tarfile.GNU_FORMAT &nbsp; &nbsp; _used by: create_\
  Double Commander fails to correctly display mtime when PAX is used, therefore GNU is the default
* **source_dir**: str &nbsp; &nbsp; _used by: create_\
  path to the directory which is to be archived
* **included_top_dirs**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  a list of paths\
  if present, only files from those dirs and their descendant subdirs will be considered, together with _**included_files_as_glob**_\
  the paths can be relative to _**source_dir**_ or absolute, but always under _**source_dir**_\
  if missing, _**source_dir**_ and all its descendant subdirs will be considered
* **excluded_top_dirs**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  like _**included_top_dirs**_, but for exclusion
* **included_dirs_as_regex**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  a list of regex patterns, applied after _**..._top_dirs**_ and dirnames of _**..._files_as_glob**_\
  if present, only matching directories will be included\
  `/` must be used as the path separator, also on MS Windows\
  the patterns are matched against a path relative to _**source_dir**_\
  the first segment in the relative path (to match against) also starts with a slash\
  e.g. `['/B$',]` will match any basename equal to `B`, at any level\
  regex-pattern matching is case-sensitive – use `(?i)` at each pattern's beginning for case-insensitive matching\
  see also https://docs.python.org/3/library/re.html
* **excluded_dirs_as_regex**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  like _**included_dirs_as_regex**_, but for exclusion
* **included_files_as_glob**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  a list of glob patterns, also known as shell-style wildcards, i.e. `* ? [seq] [!seq]`\
  if present, only matching files will be considered, together with files from _**included_top_dirs**_\
  the paths/globs can be partial, relative to _**source_dir**_ or absolute, but always under _**source_dir**_\
  e.g. `["My Music\*.m3u"]`\
  on MS Windows, global-pattern matching is case-insensitive\
  caution: a leading path separator in a path/glob indicates a root directory, e.g. `["\My Music\*"]`\
  means `C:\My Music\*` or `D:\My Music\*` but not `C:\Users\Mac\Documents\My Music\*`\
  see also https://docs.python.org/3/library/fnmatch.html and https://en.wikipedia.org/wiki/Glob_(programming)
* **excluded_files_as_glob**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  like _**included_files_as_glob**_, but for exclusion
* **included_files_as_regex**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  like _**included_dirs_as_regex**_, but for files\
  applied after _**..._top_dirs**_ and _**..._dirs_as_regex**_ and _**..._files_as_glob**_
* **excluded_files_as_regex**: list[str] &nbsp; &nbsp; _used by: create, sweep_\
  like _**included_files_as_regex**_, but for exclusion
* **sha256_comparison_if_same_size**: bool = False &nbsp; &nbsp; _used by: create_\
  when False, a file is considered changed if its mtime is later than the latest backup's mtime and its size changed\
  when True, SHA256 checksum is calculated to determine if the file changed despite having the same size\
  _mtime := time of last modification_\
  see also https://en.wikipedia.org/wiki/File_verification
* **file_deduplication**: bool = False &nbsp; &nbsp; _used by: create_\
  when True, an attempt is made to find and skip duplicates\
  a duplicate file has the same suffix and size and part of its name, case-insensitive (suffix, name)
* **min_age_in_days_of_backups_to_sweep**: int = 2 &nbsp; &nbsp; _used by: sweep_\
  only the backups which are older than the specified number of days are considered for removal
* **number_of_backups_per_day_to_keep**: int = 2 &nbsp; &nbsp; _used by: sweep_\
  for each file, the specified number of backups per day is kept, if available\
  more backups per day might be kept to satisfy _**number_of_backups_per_week_to_keep**_ and/or _**number_of_backups_per_month_to_keep**_\
  oldest backups are removed first
* **number_of_backups_per_week_to_keep**: int = 14 &nbsp; &nbsp; _used by: sweep_\
  for each file, the specified number of backups per week is kept, if available\
  more backups per week might be kept to satisfy _**number_of_backups_per_day_to_keep**_ and/or _**number_of_backups_per_month_to_keep**_\
  oldest backups are removed first
* **number_of_backups_per_month_to_keep**: int = 60 &nbsp; &nbsp; _used by: sweep_\
  for each file, the specified number of backups per month is kept, if available\
  more backups per month might be kept to satisfy _**number_of_backups_per_day_to_keep**_ and/or _**number_of_backups_per_week_to_keep**_\
  oldest backups are removed first
* **commands_which_use_filters**: list[str] = ['create'] &nbsp; &nbsp; _used by: create, sweep_\
  determines which commands can use the filters specified in the included_* and excluded_* settings\
  by default, filters are used only by _**create**_, i.e. _**sweep**_ considers all created backups (no filter is applied)\
  a filter for _**sweep**_ could be used to e.g. never remove backups from the first day of a month:\
  `excluded_files_as_regex = ['/\d\d\d\d-\d\d-01_\d\d,\d\d,\d\d\.\d{6}(\+|-)\d\d,\d\d\~\d+(~.+)?.tar(\.(gz|bz2|xz))?$']`\
  it's best when the setting is part of a separate profile, i.e. a copy made for _**sweep**_,\
  otherwise _**create**_ will also seek such files to be excluded
<!-- settings pydoc end -->

## Logging settings

Logging is controlled by settings located in `rumar/rumar.logging.toml` inside `$XDG_CONFIG_HOME` (`$HOME/.config` if not set) on POSIX,
or inside `%APPDATA%` on NT (MS Windows).

By default, `rumar.log` is created in the current directory (where `rumar.py` is executed).\
To disable the creation of `rumar.log`,
copy the below to `rumar.logging.toml` in the appropriate location
and put a hash `#` in front of `"to_file",` in `[loggers.rumar]`.

<!-- logging settings begin -->
```toml
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
```
<!-- logging settings end -->
More information: <https://docs.python.org/3/library/logging.config.html#logging-config-dictschema>
