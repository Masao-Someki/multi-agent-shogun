"""Generate the reusable diff from preserved originals and installed sources."""
import difflib
from pathlib import Path

directory = Path(__file__).resolve().parent
site = directory.parents[1] / '.pixi/envs/default/lib/python3.12/site-packages'
parts = []
for original in sorted((directory / 'original').rglob('*.py')):
    relative = original.relative_to(directory / 'original')
    parts.extend(difflib.unified_diff(
        original.read_text().splitlines(keepends=True),
        (site / relative).read_text().splitlines(keepends=True),
        fromfile='a/' + str(relative), tofile='b/' + str(relative),
    ))
output = directory / 'vllm-0.31.0-namespace.patch'
output.write_text(''.join(parts))
print(output)
