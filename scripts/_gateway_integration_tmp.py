"""Apply the staged integration once; never shipped in the final commit."""
from pathlib import Path
import ast
import runpy

base = Path(__file__).with_name('_gateway_base_tmp.py')
followup = Path(__file__).with_name('_gateway_followup_tmp.py')
context = runpy.run_path(str(base))
exec(compile(followup.read_text(), str(followup), 'exec'), context)
for path in (Path(__file__).parent).glob('*.py'):
    ast.parse(path.read_text())
base.unlink()
followup.unlink()
print('All staged gateway sources are syntactically valid; temporary patch modules removed.')
