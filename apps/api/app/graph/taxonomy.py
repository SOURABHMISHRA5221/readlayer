"""The fixed domain taxonomy (decision 33, DESIGN §2): the only list of domains in the API.

The first four are the original business domains and keep their ids, so graphs, persona
templates, readers' θ and explanation caches made before M2.2 stay valid. The web app mirrors
this list in apps/web/src/lib/taxonomy.ts (a test keeps the two equal).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainInfo:
    id: str
    label: str
    scope: str  # one line: what belongs here (used in prompts)


TAXONOMY: tuple[DomainInfo, ...] = (
    DomainInfo("economics", "Economics", "the economy: growth, inflation, trade, jobs, money"),
    DomainInfo("finance", "Finance", "markets, investing, banking, financial instruments"),
    DomainInfo("business", "Business", "companies, industries, management, deals"),
    DomainInfo("policy", "Policy", "public policy, taxes, regulation, government schemes"),
    DomainInfo("politics", "Politics", "elections, parties, government, international relations"),
    DomainInfo("law", "Law", "laws, courts, legal procedure and rights"),
    DomainInfo(
        "technology",
        "Technology",
        "computing, software, AI, the internet, devices, engineering"
        " and energy technology (power plants, nuclear reactors, batteries)",
    ),
    DomainInfo("science", "Science", "physics, chemistry, biology, astronomy, research methods"),
    DomainInfo("health", "Health", "medicine, diseases, the body, public health"),
    DomainInfo("environment", "Environment", "climate, ecology, pollution and conservation"),
    DomainInfo("sports", "Sports", "sports, their rules, tactics and competitions"),
    DomainInfo("culture", "Culture", "arts, literature, music, film, media, philosophy"),
    DomainInfo("education", "Education", "schools, universities, teaching and learning"),
    DomainInfo("society", "Society", "social issues, communities, religion, demographics"),
)

DOMAIN_IDS: tuple[str, ...] = tuple(d.id for d in TAXONOMY)
BUSINESS_DOMAINS: tuple[str, ...] = DOMAIN_IDS[:4]
BY_ID: dict[str, DomainInfo] = {d.id: d for d in TAXONOMY}


def scope_lines() -> str:
    """`- id: scope` per domain, for prompts that ask the model to pick a domain."""
    return "\n".join(f'- "{d.id}": {d.scope}' for d in TAXONOMY)
