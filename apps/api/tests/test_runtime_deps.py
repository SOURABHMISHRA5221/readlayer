"""The production image installs without dev dependencies (`uv sync --no-dev`), so app code
must never import a dev-only package (d50's first deploy failed on `feedparser`)."""

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_app_imports_no_dev_only_package():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    runtime = {d.split("[")[0].split(">")[0].split("=")[0].strip().lower()
               for d in project["project"]["dependencies"]}  # fmt: skip
    dev_only = {d.split(">")[0].split("=")[0].strip().lower().replace("-", "_")
                for d in project["dependency-groups"]["dev"]} - runtime  # fmt: skip
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            offenders += [f"{path.relative_to(ROOT)}: {n}" for n in names
                          if n.split(".")[0].lower() in dev_only]  # fmt: skip
    assert not offenders, offenders
