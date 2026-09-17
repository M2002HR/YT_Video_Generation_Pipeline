"""One-shot integration; helpers are removed before the validated source commit."""
from pathlib import Path
import ast
import runpy

base = Path(__file__).with_name('_gateway_base_tmp.py')
helpers = [Path(__file__).with_name(name) for name in ('_gateway_followup_tmp.py', '_gateway_review_tmp.py', '_gateway_final_tmp.py', '_gateway_test_fixtures_tmp.py')]
context = runpy.run_path(str(base))
for helper in helpers:
    exec(compile(helper.read_text(), str(helper), 'exec'), context)
for path in Path(__file__).parent.glob('*.py'):
    ast.parse(path.read_text())
for path in [base, *helpers]:
    path.unlink()
print('Integration sources checked; all temporary patch helpers removed.')
