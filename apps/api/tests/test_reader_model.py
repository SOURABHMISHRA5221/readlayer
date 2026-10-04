from datetime import UTC, datetime, timedelta

import pytest

from app.reader import model
from app.reader.model import Edge, Evidence

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


def test_prior_is_the_1pl_logistic():
    assert model.prior(0.0, 0.0) == pytest.approx(0.5)
    assert model.prior(1.0, 0.0) == pytest.approx(1 / (1 + 2.718281828**-1), rel=1e-6)
    assert model.prior(-2.0, 2.0) == pytest.approx(model.sigmoid(-4.0))


def test_first_touch_uses_k_times_prior():
    edge = model.init_edge(0.3, NOW)
    assert edge.alpha == pytest.approx(0.6)
    assert edge.beta == pytest.approx(1.4)
    assert model.p_know(edge) == pytest.approx(0.3)
    assert model.confidence(edge) == pytest.approx(2.0)
    assert edge.band == "heard of"
    assert edge.band_prev is None


@pytest.mark.parametrize(
    ("p", "band"),
    [
        (0.0, "unaware"),
        (0.2499, "unaware"),
        (0.25, "heard of"),
        (0.4999, "heard of"),
        (0.5, "understands"),
        (0.7999, "understands"),
        (0.8, "can explain"),
        (1.0, "can explain"),
    ],
)
def test_bands(p, band):
    assert model.band_of(p) == band


def test_forgetting_after_90_days_halves_the_distance_to_the_prior():
    prior = 0.4
    edge = Edge(alpha=6.0, beta=1.0, last_seen=NOW - timedelta(days=90), band="can explain")
    out = model.forget(edge, prior, NOW)
    a0, b0 = 2 * prior, 2 * (1 - prior)
    assert out.alpha - a0 == pytest.approx((6.0 - a0) / 2)
    assert out.beta - b0 == pytest.approx((1.0 - b0) / 2)


def test_forgetting_is_a_no_op_at_zero_days_and_converges_to_the_prior():
    edge = Edge(alpha=5.0, beta=2.0, last_seen=NOW, band="understands")
    assert model.forget(edge, 0.3, NOW) == edge
    old = Edge(alpha=5.0, beta=2.0, last_seen=NOW - timedelta(days=3650), band="understands")
    far = model.forget(old, 0.3, NOW)
    assert far.alpha == pytest.approx(0.6, abs=1e-6)
    assert far.beta == pytest.approx(1.4, abs=1e-6)


def test_forgetting_ignores_clock_skew():
    edge = Edge(alpha=5.0, beta=2.0, last_seen=NOW + timedelta(days=1), band="understands")
    assert model.forget(edge, 0.3, NOW) == edge


def test_positive_evidence_adds_to_alpha_negative_to_beta():
    edge = model.init_edge(0.5, NOW)
    up = model.apply_evidence(edge, 0.5, "knew_this", 2.0, NOW)
    assert (up.alpha, up.beta) == pytest.approx((3.0, 1.0))
    down = model.apply_evidence(edge, 0.5, "explain_opened", -1.0, NOW)
    assert (down.alpha, down.beta) == pytest.approx((1.0, 2.0))
    assert down.evidence[-1] == Evidence("explain_opened", -1.0, NOW)


def test_evidence_applies_forgetting_first_and_moves_last_seen():
    prior = 0.5
    edge = Edge(alpha=5.0, beta=1.0, last_seen=NOW - timedelta(days=90), band="can explain")
    out = model.apply_evidence(edge, prior, "knew_this", 2.0, NOW)
    assert out.alpha == pytest.approx(1 + (5 - 1) / 2 + 2.0)
    assert out.beta == pytest.approx(1.0)
    assert out.last_seen == NOW


def test_evidence_keeps_the_last_20_items():
    edge = model.init_edge(0.5, NOW)
    for i in range(25):
        edge = model.apply_evidence(edge, 0.5, "knew_this", 0.1, NOW + timedelta(seconds=i))
    assert len(edge.evidence) == model.MAX_EVIDENCE == 20
    assert edge.evidence[-1].at == NOW + timedelta(seconds=24)
    assert edge.evidence[0].at == NOW + timedelta(seconds=5)


def test_band_change_records_previous_band_and_time():
    edge = model.init_edge(0.3, NOW)  # heard of
    later = NOW + timedelta(hours=1)
    up = model.apply_evidence(edge, 0.3, "knew_this", 2.0, later)  # 2.6/4 = 0.65
    assert up.band == "understands"
    assert up.band_prev == "heard of"
    assert up.band_changed_at == later
    same = model.apply_evidence(up, 0.3, "read_normal_no_hover", 0.3, later + timedelta(hours=1))
    assert same.band == "understands"
    assert same.band_prev == "heard of"
    assert same.band_changed_at == later


def test_evidence_weights_match_design_section_4():
    w = model.EVIDENCE_WEIGHTS
    assert w["knew_this"] == 2.0
    assert w["explain_opened"] == -1.0
    assert w["explain_helpful"] == -0.5
    assert w["text_searched"] == -1.0
    assert w["read_normal_no_hover"] == 0.3
    assert w["slowdown"] == -0.3
    assert w["liked_article_mention"] == 0.2
    assert model.STRONG_EVIDENCE == 3.0  # calibration, quiz, explicit correction


def test_elo_update():
    assert model.elo(0.0, 1.0, 0.0, 0.1) == pytest.approx(0.05)
    assert model.elo(0.0, 0.0, 0.0, 0.3) == pytest.approx(-0.15)
    # A surprising success moves θ more than an expected one.
    assert model.elo(0.0, 1.0, 2.0, 0.1) > model.elo(0.0, 1.0, -2.0, 0.1)
    assert model.ELO_K == 0.1
    assert model.ELO_K_ONBOARDING == 0.3


def test_current_view_applies_forgetting_without_touching_the_edge():
    edge = Edge(alpha=6.0, beta=1.0, last_seen=NOW - timedelta(days=90), band="can explain")
    p = model.current_p_know(edge, 0.4, NOW)
    assert p == pytest.approx(model.p_know(model.forget(edge, 0.4, NOW)))
    assert edge.alpha == 6.0
