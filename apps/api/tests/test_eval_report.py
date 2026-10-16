"""Decision 67 L2: experiment runs (a thinking level or a forced frame) never stand for the
served config anywhere in the eval report."""

import shutil
from pathlib import Path

from evals import report

RESULTS = Path(report.__file__).parent / "results"
BASELINE = "20261016T144416_d67-baseline.json"
EXPERIMENT = "20261016T144750_d67-drafts-low.json"


def test_report_sections_use_the_served_baseline_not_the_later_experiment(tmp_path, monkeypatch):
    for name in (BASELINE, EXPERIMENT):
        shutil.copy(RESULTS / name, tmp_path / name)
    monkeypatch.setattr(report, "RESULTS", tmp_path)
    monkeypatch.setattr(report, "REPORT", tmp_path / "report.md")
    monkeypatch.setattr(report, "CHANGELOG", tmp_path / "none.md")
    report.write_report()
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    sections = {s.split("\n", 1)[0]: s for s in md.split("\n## ")}

    def section(title: str) -> str:
        return next(v for k, v in sections.items() if k.startswith(title))

    assert f"(`{BASELINE}`)" in section("Which layer caught each adversarial card")
    for title in (
        "Which layer caught",
        "Good cards the verifier rejected",
        "Injection cases",
        "Cost",
    ):
        assert EXPERIMENT not in section(title)
    assert "rejected_twice" not in section("Injection cases")  # I06 was verified on the retry
    assert "$0.0085" in section("Cost") and "$0.0057" not in section("Cost")
