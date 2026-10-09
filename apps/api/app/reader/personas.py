"""Demo personas as seeded reader graphs (DESIGN §4, decision 7). Pure: no I/O.

Each persona is θ per domain plus anchor concepts it knows well and concepts it doesn't.
`build_template` expands the anchors through the prerequisite DAG: knowing a concept implies
knowing its prerequisites; not knowing one implies not knowing what directly builds on it.
Explicit anchors win over expansion, known expansion over gap expansion. Every seeded edge
carries one `seed` evidence entry. `scripts/seed_personas.py` writes the result to
`persona_templates/{persona}`; demo readers read it until their first event, then get a copy.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.graph.graph import ConceptGraph
from app.reader import model
from app.reader.model import Edge, Evidence
from app.reader.state import PersonaKey, ThinksIn

# (p_know, confidence α+β) per seeded edge kind.
KNOWN = (0.85, 6.0)
KNOWN_PREREQ = (0.8, 5.0)
GAP = (0.15, 3.0)
GAP_DEPENDENT = (0.2, 2.5)
MAX_GAP_DEPENDENTS = 40  # per persona, so one basic gap can't seed half the graph


@dataclass(frozen=True)
class PersonaSpec:
    label: str
    theta: Mapping[str, float]
    knows: tuple[str, ...]
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class PersonaTemplate:
    key: PersonaKey
    graph_version: str
    theta: Mapping[str, float]
    edges: Mapping[str, Edge]
    missing: tuple[str, ...]  # anchor ids not in this graph version

    @property
    def version(self) -> str:
        return f"{self.key}@{self.graph_version}"


PERSONAS: Mapping[PersonaKey, PersonaSpec] = {
    "newcomer": PersonaSpec(
        "Newcomer (engineer)",
        {"economics": -1.2, "finance": -1.0, "business": -0.3, "policy": -0.5},
        knows=(
            "c_inflation",
            "c_interest_rates",
            "c_budget",
            "c_recession",
            "c_revenues",
            "c_profit_margins",
            "c_supply_chain",
            "c_semiconductors",
            "c_data_center",
            "c_ai",
            "c_upi",
            "c_economies_of_scale",
            "c_monopoly",
            "c_opportunity_cost",
            "c_equities",
            "c_mutual_funds",
            "c_dividends",
            "c_s_p_500",
            "c_credit_score",
            "c_market_capitalization",
            "c_ipo",
            "c_exchange_traded_fund",
            "c_large_cap",
            "c_valuation",
        ),
        gaps=(
            "c_yield_curve",
            "c_bond_yields",
            "c_repo_rate",
            "c_basis_points",
            "c_quantitative_easing",
            "c_fiscal_deficit",
            "c_open_market_operation_omo",
            "c_derivative_contracts",
            "c_foreign_portfolio_investor_fpi",
            "c_monetary_tightening",
            "c_cash_reserve_ratio_crr",
            "c_fiscal_consolidation",
            "c_current_account_deficit",
            "c_government_bonds",
            "c_us_treasury_bonds",
            "c_treasury_bill",
            "c_federal_funds_rate",
            "c_foreign_exchange_reserves",
            "c_monetary_policy_committee",
            "c_inflation_targeting",
        ),
    ),  # fmt: skip
    "trader": PersonaSpec(
        "Markets trader",
        {"finance": 1.5, "business": 0.8, "economics": -0.3, "policy": -1.0},
        knows=(
            "c_bond_yields",
            "c_equities",
            "c_repo_rate",
            "c_market_liquidity",
            "c_us_treasury_bonds",
            "c_nifty_50",
            "c_basis_points",
            "c_fixed_income",
            "c_spread",
            "c_leverage",
            "c_derivative_contracts",
            "c_treasury_yields",
            "c_yield_curve",
            "c_volatility",
            "c_short_positions",
            "c_hedge",
            "c_arbitrage",
            "c_coupon",
            "c_ipo",
            "c_market_capitalization",
            "c_federal_funds_rate",
            "c_credit_risk",
            "c_s_p_500",
            "c_foreign_portfolio_investor_fpi",
        ),
        gaps=(
            "c_fiscal_consolidation",
            "c_fiscal_space",
            "c_capital_controls",
            "c_office_for_budget_responsibility",
            "c_fiscal_rules",
            "c_macroprudential_policy",
            "c_keynesian_economics",
            "c_phillips_curve",
            "c_monetarism",
            "c_capital_account",
            "c_crowding_out",
            "c_output_gap",
            "c_sez",
        ),
    ),  # fmt: skip
    "policy_student": PersonaSpec(
        "Policy student",
        {"economics": 1.2, "policy": 1.5, "finance": -1.0, "business": -0.4},
        knows=(
            "c_monetary_policy",
            "c_inflation",
            "c_central_bank",
            "c_cpi",
            "c_fiscal_deficit",
            "c_aggregate_demand",
            "c_quantitative_easing",
            "c_keynesian_economics",
            "c_phillips_curve",
            "c_inflation_targeting",
            "c_fiscal_policy",
            "c_fiscal_consolidation",
            "c_fiscal_space",
            "c_monetary_policy_committee",
            "c_balance_of_payments",
            "c_current_account_deficit",
            "c_liquidity_trap",
            "c_crowding_out",
            "c_output_gap",
            "c_rbi",
            "c_federal_reserve",
            "c_macroprudential_policy",
            "c_repo_rate",
            "c_government_bonds",
            "c_bond_yields",
            "c_interest_rates",
            "c_treasury_bill",
            "c_foreign_exchange_reserves",
            "c_cash_reserve_ratio_crr",
            "c_federal_funds_rate",
            "c_us_treasury_bonds",
            "c_bank_reserves",
            "c_capital_requirements",
            "c_sovereign_default",
            "c_open_market_operation_omo",
            "c_money_supply",
        ),
        gaps=(
            "c_derivative_contracts",
            "c_short_positions",
            "c_arbitrage",
            "c_expiry_days",
            "c_foreign_exchange_swaps",
            "c_mortgage_backed_security",
            "c_asset_backed_security",
            "c_margins",
            "c_market_capitalization",
            "c_private_equity",
            "c_hedge_fund",
            "c_leverage",
            "c_par_value",
            "c_nifty_50",
            "c_bse_sensex",
            "c_ipo",
            "c_exchange_traded_fund",
            "c_large_cap",
            "c_valuation",
            "c_s_p_500",
        ),
    ),  # fmt: skip
}

# Each persona's analogy frame for explanations (DESIGN §7). Code, not template data, so a
# change needs no re-seed. Newcomer is an engineer; the frames differ so the demo shows it.
PERSONA_THINKS_IN: Mapping[PersonaKey, ThinksIn] = {
    "newcomer": "software",
    "trader": "cricket",
    "policy_student": "law",
}


def _edge(kind: tuple[float, float], now: datetime) -> Edge:
    p, conf = kind
    alpha, beta = p * conf, (1 - p) * conf
    w = alpha - beta  # signed: the seed's net claim
    return Edge(
        alpha=alpha,
        beta=beta,
        last_seen=now,
        band=model.band_of(p),
        evidence=(Evidence("seed", w, now),),
    )


def build_template(
    key: PersonaKey, spec: PersonaSpec, graph: ConceptGraph, now: datetime
) -> PersonaTemplate:
    present = [c for c in (*spec.knows, *spec.gaps) if graph.get(c) is not None]
    missing = tuple(c for c in (*spec.knows, *spec.gaps) if graph.get(c) is None)
    knows = [c for c in spec.knows if c in present]
    gaps = [c for c in spec.gaps if c in present]
    anchors = set(knows) | set(gaps)

    kinds: dict[str, tuple[float, float]] = {}
    for cid in gaps:
        for dep in sorted(d.id for d in graph.dependents(cid)):
            if len(kinds) >= MAX_GAP_DEPENDENTS:
                break
            if dep not in anchors:
                kinds[dep] = GAP_DEPENDENT
    for cid in knows:  # known expansion overrides gap expansion
        for anc in sorted(graph.ancestors(cid)):
            if anc not in anchors:
                kinds[anc] = KNOWN_PREREQ
    kinds |= dict.fromkeys(gaps, GAP)
    kinds |= dict.fromkeys(knows, KNOWN)
    edges = {cid: _edge(kind, now) for cid, kind in sorted(kinds.items())}
    return PersonaTemplate(key, graph.version, dict(spec.theta), edges, missing)
