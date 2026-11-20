"""Read-only offline QA. Does NOT prove live SpaceMolt authentication or A2A gameplay."""
import ast
from pathlib import Path
from scripts.self_test import main as smoke

ROOT = Path(__file__).resolve().parents[1]

def main():
    skip = {'.venv', 'venv', 'site-packages', '__pycache__', '.git'}
    py_files = sorted(p for p in ROOT.rglob('*.py') if not skip.intersection(p.relative_to(ROOT).parts))
    for path in py_files:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    print(f'[PASS] Parsed {len(py_files)} Python source files')
    smoke()
    worker = (ROOT/'examples'/'a2a_worker.py').read_text(encoding='utf-8')
    discovery = (ROOT/'examples'/'mcp_discover.py').read_text(encoding='utf-8')
    assert 'from a2a.helpers import get_message_text' in worker
    assert 'as (read,write):' in discovery and 'tool.input_schema' in discovery
    print('[PASS] Instructor-tested MCP/A2A API corrections present')

if __name__ == '__main__':
    main()
