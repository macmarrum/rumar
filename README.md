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
5. Run `python -m pip install tomli` to install the module [tomli](https://pypi.org/project/tomli/), if not yet installed
6. Run `python rumar.py --list` to list your profiles; you should see your profile name printed in the console
7. Run `python rumar.py --profile "My Documents" --create` to create a backup of the profile "My Documents"
8. Add this command to Task Scheduler or cron, to be run at an interval or each day/night

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
excluded_files_as_regex = ['^(desktop\.ini|thumbs\.db)$']
excluded_dirs_as_regex = ['^/(My Music|My Pictures|My Videos)$']
```

### Settings details

* `profile`: str\
  name of the profile
* `backup_base_dir`: str\
  path to the base directory used for backup; usually set in the global space, common for all profiles\
  backup dir for each profile is constructed as backup_base_dir + profile, unless backup_base_dir_for_profile is set, which takes precedence
* `backup_base_dir_for_profile`: str = None\
  path to the base dir used for the profile; usually left unset; see backup_base_dir
* `archive_format`: Literal[tar, tar.gz, tar.bz2, tar.xz] = 'tar.gz'\
    archive file to be created
* `compression_level`: int = 3\
    for formats tgz, tbz, txz: compression level from 0 to 9
* `no_compression_suffixes_default`: str = '7z,zip,jar,rar,tgz,gz,tbz,bz2,xz,zst,zstd,xlsx,docx,pptx,ods,odt,odp,odg,odb,epub,mobi,png,jpg,mp4,mov,mp3,m4a,aac,ogg,ogv,kdbx'\
    comma-separated string of lower-case suffixes for which to use uncompressed tar
* `no_compression_suffixes`: str = ''\
    extra lower-case suffixes in addition to no_compression_suffixes_default
* `tar_format`: Literal[0, 1, 2] = tarfile.GNU_FORMAT\
  DoubleCmd fails to correctly display mtime when PAX is used – GNU is recommended
* `source_dir`: str\
  path to the root directory that is to be archived
* `source_files`: Optional[list[str]]\
  if present, only these files are considered\
  can be relative to source_dir or absolute (but under source_dir)\
  on Windows, if absolute, must use the source_dir-drive-letter case (upper or lower)
* `excluded_files_as_regex`, `excluded_dirs_as_regex`: Optional[list[str]]\
  regex defining files or dirs (recursively) to be excluded, relative to source_dir\
  must use `/` also on Windows\
  the first segment in the relative path (to match against) also starts with a slash\
  e.g. `['/B$',]` will exclude any basename equal to B, at any level
* `sha256_comparison_if_same_size`: bool = False\
  when False, a file is considered changed if its mtime is later than the latest backup's mtime and its size changed\
  when True, SHA256 checksum is compared to determine if the file changed despite having the same size
* `age_threshold_of_backups_to_sweep`: int = 2\
  when `sweep` is used, consider for removal only such backups which are older than X days
* `number_of_daily_backups_to_keep:` int = 2
* `number_of_weekly_backups_to_keep:` int = 14
* `number_of_monthly_backups_to_keep:` int = 60\
  when `sweep` is used, remove backups if their number per file is above the setting per day and week and month
