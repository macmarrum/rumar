# Copyright © 2023, 2024 macmarrum (at) outlook (dot) ie
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from rumar import LOGGING_TOML_DEFAULT

me = Path(__file__)
UTF8 = 'UTF-8'

readme_md_path = me.parent.parent / 'README.md'
lines = []
is_settings = False
for line in readme_md_path.read_text(encoding=UTF8).splitlines():
    if line.startswith('<!-- logging settings begin -->'):
        is_settings = True
        lines.append(line)
    if line.startswith('<!-- logging settings end -->'):
        is_settings = False
        lines.append('```toml')
        lines += LOGGING_TOML_DEFAULT.splitlines()
        lines.append('```')
    if not is_settings:
        lines.append(line)
text = '\n'.join(lines) + '\n'
readme_md_path.rename(readme_md_path.with_suffix('.bak'))
readme_md_path.write_text(text, encoding=UTF8)
