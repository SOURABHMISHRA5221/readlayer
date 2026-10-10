"""M2: ingest every URL in data/corpus_urls.txt into Firestore demand profiles.

Run:  cd apps/api && uv run python -m scripts.ingest_corpus [--sample 20] [--retry-failed]

Resumable: a URL already in the content store costs nothing (ingest_url's cache), and
data/ingest_state.jsonl remembers permanent failures so reruns skip them. Failures are logged and
skipped; a spent daily LLM budget stops the run cleanly, and rerunning continues where it stopped.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import litellm

from app import llm
from app.config import get_settings
from app.ingest.models import ContentDoc
from app.ingest.safe_fetch import FetchError
from app.ingest.service import ingest_url
from app.ingest.urls import url_hash
from app.log import configure_logging
from app.store.content_repo import get_content_store

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
CORPUS_FILE = DATA_DIR / "corpus_urls.txt"
STATE_FILE = DATA_DIR / "ingest_state.jsonl"

CONCURRENCY = 4
WIKI_SOURCE = "wikipedia"
PROJECTION_CAP_USD = 10.0
PERMANENT_CODES = {"unsafe_url", "robots_disallowed", "not_html", "too_large", "no_article_text"}

# Build-cost estimate for the pilot projection (scripts/build_concepts.py call shapes).
EST_CONCEPTS = 3000  # deliberately high; a few thousand at most per CLAUDE.md
EST_BUILD_CALLS = EST_CONCEPTS / 25 + EST_CONCEPTS / 15 + EST_CONCEPTS / 20 + 40  # define,
# prereqs, merge checks, dedupe band check
EST_TOKENS_IN, EST_TOKENS_OUT = 4000, 2000  # per build call, generous


@dataclass(frozen=True)
class CorpusEntry:
    url: str
    source: str
    domain: str = ""  # held-out list only (M2.2): the taxonomy domain, fixed before measuring


@dataclass(frozen=True)
class Outcome:
    url: str
    source: str
    status: str  # "ok" | "failed"
    code: str | None = None
    http_status: int | None = None
    new: bool = False  # True when this run paid for the ingestion
    cost_usd: float = 0.0  # the doc's ingestion cost (paid now or earlier)
    demands: int = 0
    at: str = ""


# ---------------------------------------------------------------- pure helpers


def parse_corpus(lines: Iterable[str]) -> list[CorpusEntry]:
    entries, seen = [], set()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url, source, domain = (line.split("\t") + ["", ""])[:3]
        if url in seen:
            continue
        seen.add(url)
        entries.append(CorpusEntry(url.strip(), source.strip() or "unknown", domain.strip()))
    return entries


def interleave_sources(entries: list[CorpusEntry]) -> list[CorpusEntry]:
    """Round-robin by source so concurrent workers spread over different sites."""
    by_source: dict[str, list[CorpusEntry]] = defaultdict(list)
    for e in entries:
        by_source[e.source].append(e)
    queues = list(by_source.values())
    out = []
    for i in range(max((len(q) for q in queues), default=0)):
        out.extend(q[i] for q in queues if i < len(q))
    return out


def stratified_sample(entries: list[CorpusEntry], n: int) -> list[CorpusEntry]:
    """Wikipedia in proportion to its share; the rest split evenly across news sources."""
    wiki = [e for e in entries if e.source == WIKI_SOURCE]
    news = [e for e in entries if e.source != WIKI_SOURCE]
    n_wiki = min(len(wiki), round(n * len(wiki) / max(len(entries), 1)))
    picked = interleave_sources(news)[: n - n_wiki]
    return picked + wiki[:n_wiki]


def is_permanent(outcome: Outcome) -> bool:
    if outcome.code in PERMANENT_CODES:
        return True
    return outcome.http_status is not None and 400 <= outcome.http_status < 500


def should_attempt(last: Outcome | None, retry_failed: bool) -> bool:
    if last is None:
        return True
    if last.status == "ok":
        return False
    return retry_failed or not is_permanent(last)


def doc_cost(doc: ContentDoc) -> float:
    return sum(c.cost_usd for c in doc.llm_calls)


@dataclass(frozen=True)
class Projection:
    news_mean: float
    wiki_mean: float
    ingest_usd: float
    build_usd: float

    @property
    def total_usd(self) -> float:
        return self.ingest_usd + self.build_usd


def project_cost(
    outcomes: list[Outcome], news_total: int, wiki_total: int, build_usd: float
) -> Projection:
    """Projected total cost of ingesting the whole corpus plus the concept build."""
    paid = [o for o in outcomes if o.status == "ok"]
    news = [o.cost_usd for o in paid if o.source != WIKI_SOURCE]
    wiki = [o.cost_usd for o in paid if o.source == WIKI_SOURCE]
    news_mean = sum(news) / len(news) if news else 0.0
    wiki_mean = sum(wiki) / len(wiki) if wiki else news_mean
    ingest = news_mean * news_total + wiki_mean * wiki_total
    return Projection(news_mean, wiki_mean, ingest, build_usd)


def estimate_build_cost(model: str) -> float:
    try:
        cost_in, cost_out = litellm.cost_per_token(
            model=model, prompt_tokens=EST_TOKENS_IN, completion_tokens=EST_TOKENS_OUT
        )
    except Exception:
        overrides = get_settings().model_price_overrides
        if model not in overrides:
            return float("nan")
        p_in, p_out = overrides[model]
        cost_in, cost_out = EST_TOKENS_IN * p_in, EST_TOKENS_OUT * p_out
    return (cost_in + cost_out) * EST_BUILD_CALLS


# ---------------------------------------------------------------- state file


def load_state(path: Path = STATE_FILE) -> dict[str, Outcome]:
    """Last outcome per URL (the file is append-only)."""
    state: dict[str, Outcome] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = Outcome(**json.loads(line))
                state[o.url] = o
    return state


def append_state(outcome: Outcome, path: Path = STATE_FILE) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(outcome)) + "\n")


# ---------------------------------------------------------------- run

Ingest = Callable[[str], Awaitable[ContentDoc]]


async def ingest_one(entry: CorpusEntry, ingest: Ingest) -> Outcome:
    now = datetime.now(UTC).isoformat()
    base = {"url": entry.url, "source": entry.source, "at": now}
    try:
        new = await get_content_store().get(url_hash(entry.url)) is None
        doc = await ingest(entry.url)
    except FetchError as exc:
        return Outcome(**base, status="failed", code=exc.code, http_status=exc.status)
    except (llm.LLMUnavailable, llm.LLMRejected) as exc:
        return Outcome(**base, status="failed", code=type(exc).__name__)
    return Outcome(**base, status="ok", new=new, cost_usd=doc_cost(doc), demands=len(doc.demands))


async def run(
    entries: list[CorpusEntry],
    ingest: Ingest = ingest_url,
    record: Callable[[Outcome], None] = append_state,
    concurrency: int = CONCURRENCY,
) -> tuple[list[Outcome], bool]:
    """Returns the outcomes and whether the daily budget stopped the run."""
    sem = asyncio.Semaphore(concurrency)
    budget_hit = asyncio.Event()
    outcomes: list[Outcome] = []

    async def worker(entry: CorpusEntry) -> None:
        async with sem:
            if budget_hit.is_set():
                return
            try:
                outcome = await ingest_one(entry, ingest)
            except llm.BudgetExceeded:
                budget_hit.set()
                return
            except Exception as exc:  # unexpected: log and keep going
                outcome = Outcome(
                    entry.url,
                    entry.source,
                    "failed",
                    code=f"error:{type(exc).__name__}",
                    at=datetime.now(UTC).isoformat(),
                )
            record(outcome)
            outcomes.append(outcome)
            mark = "ok " if outcome.status == "ok" else "ERR"
            detail = f"${outcome.cost_usd:.4f}" if outcome.status == "ok" else outcome.code
            print(f"[{len(outcomes):3}] {mark} {entry.source:12} {detail}  {entry.url}")

    await asyncio.gather(*(worker(e) for e in entries))
    return outcomes, budget_hit.is_set()


def summarize(entries: list[CorpusEntry], state: dict[str, Outcome]) -> None:
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    failures: Counter[str] = Counter()
    for e in entries:
        o = state.get(e.url)
        status = "pending" if o is None else o.status
        by_source[e.source][status] += 1
        if o is not None and o.status == "failed":
            failures[f"{o.code}{f' {o.http_status}' if o.http_status else ''}"] += 1
    print("\n=== Ingestion state ===")
    for source, counts in by_source.items():
        print(
            f"{source:14} ok={counts['ok']:3} failed={counts['failed']:3} "
            f"pending={counts['pending']:3}"
        )
    total_ok = sum(c["ok"] for c in by_source.values())
    print(f"{'total':14} ok={total_ok}")
    if failures:
        print("failures: " + ", ".join(f"{k}×{v}" for k, v in failures.most_common()))
    spent = sum(o.cost_usd for o in state.values() if o.status == "ok")
    print(f"ingestion LLM cost of ingested docs: ${spent:.4f}")


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging("WARNING")
    entries = parse_corpus(CORPUS_FILE.read_text(encoding="utf-8").splitlines())
    state = load_state()
    todo = [e for e in entries if should_attempt(state.get(e.url), args.retry_failed)]
    if args.sample:
        todo = stratified_sample(todo, args.sample)
    todo = interleave_sources(todo)
    print(f"{len(entries)} corpus URLs, {len(todo)} to attempt this run")

    outcomes, budget_hit = await run(todo)
    state = load_state()
    summarize(entries, state)
    print(
        f"LLM spend today: ${await llm.get_spend_store().get_today():.4f} "
        f"of ${settings.llm_daily_budget_usd:.2f} daily budget"
    )
    if budget_hit:
        print("STOPPED: daily LLM budget reached; rerun to continue.")
        return 2

    if args.sample:
        news_total = sum(1 for e in entries if e.source != WIKI_SOURCE)
        wiki_total = len(entries) - news_total
        build = estimate_build_cost(settings.model_fast)
        p = project_cost(outcomes, news_total, wiki_total, build)
        print("\n=== Cost projection ===")
        print(
            f"mean per news doc ${p.news_mean:.5f} × {news_total}, "
            f"per wiki doc ${p.wiki_mean:.5f} × {wiki_total}"
        )
        print(
            f"ingestion ${p.ingest_usd:.3f} + concept build (upper bound) "
            f"${p.build_usd:.3f} = ${p.total_usd:.3f}"
        )
        if not p.total_usd <= PROJECTION_CAP_USD:
            print(f"STOP: projection exceeds ${PROJECTION_CAP_USD:.0f}")
            return 3
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, help="stratified pilot of N URLs")
    parser.add_argument("--retry-failed", action="store_true", help="also retry permanent failures")
    sys.exit(asyncio.run(main(parser.parse_args())))
