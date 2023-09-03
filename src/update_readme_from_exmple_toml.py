from pathlib import Path

me = Path(__file__)
UTF8 = 'UTF-8'

toml_text = Path(me.parent.parent / 'examples' / 'rumar.toml').read_text(encoding=UTF8)
readme_md_path = me.parent.parent / 'README.md'
lines = []
is_toml_example = False
for line in readme_md_path.read_text(encoding=UTF8).splitlines():
    if line.startswith('<!-- rumar.toml example begin -->'):
        is_toml_example = True
        lines.append(line)
    if line.startswith('<!-- rumar.toml example end -->'):
        is_toml_example = False
        lines.append('```toml')
        lines += toml_text.splitlines()
        lines.append('```')
    if not is_toml_example:
        lines.append(line)
text = '\n'.join(lines)
readme_md_path.rename(readme_md_path.with_suffix('.bak'))
readme_md_path.write_text(text, encoding=UTF8)
