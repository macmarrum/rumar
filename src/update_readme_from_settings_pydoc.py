import re
from pathlib import Path
from textwrap import dedent

from rumar import Settings

me = Path(__file__)
UTF8 = 'UTF-8'

doc = dedent(Settings.__doc__)
doc = doc + 'EOF'  # add to the last line for the addition of \ to work globally
doc = re.compile(r'^(?=\w)', re.M).sub('* ', doc)
doc = re.compile(r'\n +(used by: .*)', re.M).sub(r' &nbsp; &nbsp; _\1_', doc)
doc = re.compile(r'$(?!\n\*)', re.M).sub(r'\\', doc)
doc = '\n'.join(doc.splitlines()[3:-1])  # skip profile and '* EOF\'
doc = re.compile(r'(?<=^\* )(\w+)', re.M).sub(r'**\1**', doc)
# print(doc)
readme_md_path = me.parent.parent / 'README.md'
lines = []
is_settings = False
for line in readme_md_path.read_text(encoding=UTF8).splitlines():
    if line.startswith('<!-- settings pydoc begin -->'):
        is_settings = True
        lines.append(line)
    if line.startswith('<!-- settings pydoc end -->'):
        is_settings = False
        lines += doc.splitlines()
    if not is_settings:
        lines.append(line)
text = '\n'.join(lines) + '\n'
readme_md_path.rename(readme_md_path.with_suffix('.bak'))
readme_md_path.write_text(text, encoding=UTF8)
