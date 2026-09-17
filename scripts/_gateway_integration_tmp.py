"""One-shot integration; all patch helpers are removed before validation is committed."""
from pathlib import Path
import ast
import runpy

base = Path(__file__).with_name('_gateway_base_tmp.py')
helpers = [Path(__file__).with_name(name) for name in ('_gateway_followup_tmp.py', '_gateway_review_tmp.py')]
context = runpy.run_path(str(base))
for helper in helpers:
    exec(compile(helper.read_text(), str(helper), 'exec'), context)
for path in Path(__file__).parent.glob('*.py'):
    ast.parse(path.read_text())
for path in [base, *helpers]:
    path.unlink()
print('Integration sources validated syntactically; temporary patch helpers removed.')
