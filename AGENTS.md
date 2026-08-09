# Notes for AI Agents

- **Groovy-like string quotations** wherever possible, i.e.,
double quotes for f-strings — also when triple: `f"""..."""`,
otherwise, single quotes — also when triple: `r'''...'''`,
but allow exceptions to avoid escaping quotes in strings
- **Allowed line length** is 300 (aka hard wrap columns)
- **No comments or \_\_doc\_\_** in final code — use self-documenting naming
- **Incremental refactoring** — small testable steps with commits after each step
- **Extract only what's used** — avoid speculative generality
- **Single responsibility** — each extracted class should have clear purpose
- **Remove unused imports** — Clean up imports after coding changes to keep code tidy
