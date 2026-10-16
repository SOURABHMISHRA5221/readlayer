"""Decision 67 L2/A5: experiment runs (thinking levels other than the served ones, or a forced
frame) never stand for the served config anywhere in the eval report."""

import shutil
from pathlib import Path

from evals import report

RESULTS = Path(report.__file__).parent / "results"
SERVED = "20261016T144750_d67-drafts-low.json"  # the served levels since Sourabh's yes
EXPERIMENTS = ("20261016T144416_d67-baseline.json", "20261016T150141_d67-frame-finance.json")


def test_report_sections_use_the_served_run_not_experiments(tmp_path, monkeypatch):
    for name in (SERVED, *EXPERIMENTS):
        shutil.copy(RESULTS / name, tmp_path / name)
    monkeypatch.setattr(report, "RESULTS", tmp_path)
    monkeypatch.setattr(report, "REPORT", tmp_path / "report.md")
    monkeypatch.setattr(report, "CHANGELOG", tmp_path / "none.md")
    report.write_report()
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    sections = {s.split("\n", 1)[0]: s for s in md.split("\n## ")}

    def section(title: str) -> str:
        return next(v for k, v in sections.items() if k.startswith(title))

    assert f"(`{SERVED}`)" in section("Which layer caught each adversarial card")
    for title in (
        "Which layer caught",
        "Good cards the verifier rejected",
        "Injection cases",
        "Cost",
    ):
        assert not any(e in section(title) for e in EXPERIMENTS)
    assert "$0.0057" in section("Cost") and "$0.0099" not in section("Cost")
    assert "8.5 s / 22.9 s" in section("Judge comparison")


def test_experimental_compares_with_the_served_levels():
    def run(effort, frame=None):
        return {"meta": {"reasoning_effort": effort, "frame": frame}}

    served = {"restate": "low", "explain": "low", "verify": None, "verify_background": None}
    default = dict.fromkeys(served)
    assert not report.experimental(run(served))
    assert report.experimental(run(default))
    assert report.experimental(run(served, frame="finance"))
    assert not report.experimental(run({}))  # runs recorded before levels were saved
