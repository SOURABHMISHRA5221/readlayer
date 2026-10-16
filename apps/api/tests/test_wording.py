"""Decision 67 (R2): text the API can show says "consumer", never "reader" or "Margo".

Scans every non-docstring string constant with a space in `app/`. Model-facing prompt text keeps
its wording (changing it would change the prompt and its cache keys), so it is listed here.
"""

import ast
import re
from pathlib import Path

APP = Path(__file__).parent.parent / "app"
BANNED = re.compile(r"\breaders?\b|\bMargo\b", re.IGNORECASE)
# Sent to a model, never shown: explain band rules and the onboarding phrase resolver.
MODEL_TEXT = {
    ("explain/inputs.py", "The reader has probably never met this idea."),
    ("explain/inputs.py", "The reader knows the word but not what it means."),
    ("explain/inputs.py", "The reader knows the basics."),
    ("explain/inputs.py", "The reader knows this well."),
    ("graph/resolve.py", "A reader describing what they know mentions: "),
}


def _docstrings(tree: ast.AST) -> set[int]:
    kinds = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, kinds) and node.body and isinstance(node.body[0], ast.Expr):
            out.add(id(node.body[0].value))
    return out


def _allowed(rel: str, value: str) -> bool:
    return any(rel == f and value.startswith(prefix) for f, prefix in MODEL_TEXT)


def test_api_display_text_says_consumer() -> None:
    found = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = _docstrings(tree)
        rel = path.relative_to(APP).as_posix()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            value = node.value
            if id(node) in docs or " " not in value or not BANNED.search(value):
                continue
            if not _allowed(rel, value):
                found.append(f"{rel}:{node.lineno}: {value[:80]}")
    assert found == []
