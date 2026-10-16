"""For you feed ranking (M7.5 §A.5, DESIGN §17). Pure: no I/O, no SDK, no LLM.

score = interest(topic) × format_affinity(format) × readiness × goal_boost × freshness

- interest: the reader's stored domain interest, normalised so their top topic is 1.0;
- format_affinity: the existing per-reader format model (`rank.format_affinity`);
- readiness: how many ideas the item names that are new to this reader (`named_concepts`:
  exact label/alias matches over 1–4-word n-grams of its title and snippet, single words only
  when unambiguous): 1–4 new → 1.0, none → 0.6, more than 4 → 0.8^(k−4) (too much at once);
- goal_boost: 1.3 when the item names a learning-goal target concept;
- freshness: `rank.freshness`.

Readiness shown to the reader (decision 60, DESIGN §17.2), separate from the ranking factor and
never changing the score: "familiar" (the item names only known ideas), "ready" (new ideas whose
graph prerequisites the reader knows: the map's own "ready to learn" rule, `KNOWN_P`), "stretch"
(more than READY_MAX new ideas, or a new idea with a prerequisite that is itself new: up to
READ_FIRST_MAX of those, most basic first), or None when the item names no graph concept. Based on
the ideas named in the title and summary, or, for a public library article, its key ideas
(decision 65: `attach_ideas`). The score always uses the title and summary.
"""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Literal
from urllib.parse import urlsplit

from app.graph.build import normalize_label
from app.graph.graph import ConceptGraph
from app.graph.models import Concept
from app.graph.taxonomy import BUSINESS_DOMAINS, BY_ID
from app.ingest.models import ContentDoc, is_corpus
from app.ingest.urls import url_hash
from app.reader import model
from app.reader.state import ReaderState
from app.recs.models import PODCAST_DOMAINS, Format, WebResult
from app.recs.rank import FormatPrior, FormatStats, format_affinity, freshness

READY_MIN, READY_MAX = 1, 4
READ_FIRST_MAX = 2
NOTHING_NEW = 0.6
TOO_MUCH_DECAY = 0.8
GOAL_BOOST = 1.3
MAX_ITEMS = 24
QUOTAS: Mapping[Format, int] = {"article": 3, "video": 2, "podcast": 1}
CHOSEN_QUOTAS: Mapping[Format, int] = {"article": 3, "video": 3, "podcast": 2}
OTHER_QUOTAS: Mapping[Format, int] = {"article": 2, "video": 1, "podcast": 1}


def quotas_for(formats: Iterable[str]) -> Mapping[Format, int]:
    """Decision 68 F3: per topic, a chosen format gets more slots and an unchosen one fewer;
    all three or none → QUOTAS. Pure."""
    chosen = set(formats)
    if not chosen or chosen >= {"article", "video", "podcast"}:
        return QUOTAS
    return {f: CHOSEN_QUOTAS[f] if f in chosen else OTHER_QUOTAS[f] for f in QUOTAS}


NGRAM_MAX = 4
ARTICLE_MAX_AGE = timedelta(days=14)
_WORDS = re.compile(r"[\w'’&-]+", re.UNICODE)
# Path segments of section, tag and listing pages ("latest news" searches return many of them).
HUB_SEGMENTS = frozenset(
    {"tag", "tags", "topic", "topics", "category", "categories", "section", "sections",
     "news-event", "hub", "author", "authors", "search"}
)  # fmt: skip
# Podcast-directory pages that list many shows rather than being one show or episode.
DIRECTORY_SEGMENTS = frozenset({"charts", "chart", "genre", "genres", "browse", "search", "top",
                                "category", "categories"})  # fmt: skip
SLUG_MIN_WORDS = 3
_ID_DIGITS = re.compile(r"\d{4,}")


@dataclass(frozen=True)
class FeedCandidate:
    result: WebResult
    topic: str  # taxonomy domain id
    concepts: tuple[Concept, ...] = ()  # named in title + snippet: the score uses these
    # A public library article's key ideas (decision 65): the shown readiness uses these when
    # set and non-empty; `covered` is every idea the article links (never "read up on" them).
    ideas: tuple[Concept, ...] | None = None
    covered: frozenset[str] = frozenset()


Readiness = Literal["familiar", "ready", "stretch"]
ReadinessBasis = Literal["article", "title"]


@dataclass(frozen=True)
class RankedItem:
    candidate: FeedCandidate
    score: float
    new_concepts: tuple[str, ...]  # labels new to this reader
    goal_label: str | None
    why: str
    readiness: Readiness | None = None  # shown to the reader, not part of the score
    read_first: tuple[str, ...] = ()  # prerequisites new to the reader, most basic first
    readiness_basis: ReadinessBasis = "title"


@dataclass(frozen=True)
class FeedReader:
    """What ranking needs to know about the reader, all in memory."""

    state: ReaderState
    interest: Mapping[str, float]  # domain → stored interest
    prior: FormatPrior
    stats: Mapping[Format, FormatStats] = field(default_factory=dict)
    goal_targets: Mapping[str, str] = field(default_factory=dict)  # concept id → goal label


_PLURAL_OR_POSSESSIVE = re.compile(r"['’]?s$")


def _is_caps(text: str) -> bool:
    """Written like an acronym: two or more characters, a letter, no lower-case letter (a
    trailing plural or possessive "s" aside: "IPOs", "RBI’s")."""
    core = _PLURAL_OR_POSSESSIVE.sub("", text) if len(text) > 2 else text
    return (
        len(core) >= 2 and any(ch.isalpha() for ch in core) and not any(ch.islower() for ch in core)
    )


# Domains whose plain one-word labels count for each other's items (decision 65 adds politics).
DOMAIN_GROUPS: tuple[frozenset[str], ...] = (
    frozenset(BUSINESS_DOMAINS),
    frozenset({"policy", "politics"}),
)


def _related(domain: str, topic: str) -> bool:
    return domain == topic or any(domain in g and topic in g for g in DOMAIN_GROUPS)


def _single_word_counts(concept: Concept, token: str, topic: str) -> bool:
    """One word names a concept only when that is unambiguous (decision 64). A caps-only name
    (RBI, M&A, EBITDAR) needs the word in caps too, in any domain. Otherwise only the plain
    label counts (not an alias: "stocks" → Stock variable; not a disambiguated label: "Basis
    (finance)"), and only in the item's own domain or a related one (DOMAIN_GROUPS)."""
    key = normalize_label(token)
    names = [n for n in (concept.label, *concept.aliases) if normalize_label(n) == key]
    if any(_is_caps(n) for n in names):
        return _is_caps(token)
    if normalize_label(concept.label) != key or "(" in concept.label:
        return False
    return _related(concept.domain, topic)


def named_concepts(graph: ConceptGraph, text: str, topic: str) -> tuple[Concept, ...]:
    """Graph concepts the text names: exact label/alias match over 1–4-word n-grams, longest
    first, without overlapping matches; a single word only when `_single_word_counts` (the
    item's `topic` decides the domain rule). Deterministic."""
    words = _WORDS.findall(text)
    found: dict[str, Concept] = {}
    i = 0
    while i < len(words):
        for n in range(min(NGRAM_MAX, len(words) - i), 0, -1):
            concept = graph.lookup(" ".join(words[i : i + n]))
            if concept is not None and (n > 1 or _single_word_counts(concept, words[i], topic)):
                found.setdefault(concept.id, concept)
                i += n
                break
        else:
            i += 1
    return tuple(found.values())


_SCOPE_STOP = frozenset({"and", "the", "their", "its", "of", "for", "power", "rules"})
SHORT_STEM = 4  # "tech", "econ", "educ": long labels also match their short forms
LONG_LABEL = 7


def topic_pattern(topic: str) -> re.Pattern[str]:
    """Words that say an item is about the topic: the label's stem (and, for labels of 7+
    letters, its first 4 letters), plus the words of the domain's one-line scope in the
    taxonomy ("AI", "software", "inflation"). Deterministic, no new keyword list."""
    info = BY_ID[topic]
    label = info.label.casefold()
    stems = {label[:-1] if label.endswith("s") else label}
    if len(label) >= LONG_LABEL:
        stems.add(label[:SHORT_STEM])
    scope = {w for w in re.findall(r"[a-z]{3,}|[A-Z]{2,}", info.scope)
             if w.casefold() not in _SCOPE_STOP}  # fmt: skip
    prefixes = "|".join(sorted(re.escape(s) for s in stems))
    words = "|".join(sorted(re.escape(w.casefold()) for w in scope))
    return re.compile(rf"\b(?:{prefixes})|\b(?:{words})\b")


def is_relevant(result: WebResult, topic: str, concepts: Iterable[Concept]) -> bool:
    """The item names its topic (label, short form or a scope word), or at least one concept
    of that domain (§A.2): sports news rarely says "sport", but it does name a penalty."""
    text = f"{result.title} {result.snippet}".casefold()
    if topic_pattern(topic).search(text):
        return True
    return any(c.domain == topic for c in concepts)


def _segments(url: str) -> list[str]:
    return [s for s in urlsplit(url).path.casefold().split("/") if s]


def looks_like_article(url: str) -> bool:
    """One article, not a section, tag or home page: no hub segment, and the last path segment
    is a slug of ≥ 3 words or the path carries a date or numeric id. Deterministic; a short
    real slug is the accepted loss."""
    segments = _segments(url)
    if not segments or HUB_SEGMENTS.intersection(segments):
        return False
    last = re.sub(r"\.(s?html?|php|aspx?)$", "", segments[-1])
    return len(re.split(r"[-_]+", last)) >= SLUG_MIN_WORDS or bool(
        _ID_DIGITS.search("/".join(segments))
    )


def is_listing_page(url: str, directories: Iterable[str] = ()) -> bool:
    """A podcast directory's chart, genre or browse page, or its home page (many shows, not
    one). A show hosted on its own subdomain (name.podbean.com) is not a listing."""
    segments = _segments(url)
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    return bool(DIRECTORY_SEGMENTS.intersection(segments)) or (not segments and host in directories)


NON_LATIN_MAX = 1


def is_latin_title(text: str) -> bool:
    """At most one letter outside Latin script (a stray "μ"): the explanations and the reader
    are in English, YouTube's relevanceLanguage is only a hint, and a mixed title ("ഈ റാലി
    സൂചനയോ| Political Analysis…") is mostly Latin by count (decision 64). Accents, ₹ and emoji
    pass (accents are Latin; symbols aren't letters)."""
    return (
        sum(ch.isalpha() and not (ch.isascii() or "\u00c0" <= ch <= "\u024f") for ch in text)
        <= NON_LATIN_MAX
    )


def is_feed_page(result: WebResult) -> bool:
    if not is_latin_title(result.title):
        return False
    if result.format == "article":
        return looks_like_article(result.url)
    if result.format == "podcast":
        return not is_listing_page(result.url, PODCAST_DOMAINS)
    return True


def published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def recent_enough(result: WebResult, now: datetime) -> bool:
    """Articles published within 14 days when a date is given (applied when fetching or
    seeding, never when serving a demo snapshot)."""
    if result.format != "article":
        return True
    when = published(result.published_at)
    return when is None or now - when <= ARTICLE_MAX_AGE


def readiness(new_count: int) -> float:
    if new_count == 0:
        return NOTHING_NEW
    if new_count <= READY_MAX:
        return 1.0
    return TOO_MUCH_DECAY ** (new_count - READY_MAX)


def is_new(concept: Concept, reader: ReaderState, now: datetime) -> bool:
    """New to this reader: band "unaware" or "heard of" (p_know < 0.5)."""
    p0 = model.prior(reader.theta.get(concept.domain, 0.0), concept.base_difficulty)
    edge = reader.edges.get(concept.id)
    p = model.current_p_know(edge, p0, now) if edge is not None else p0
    return p < 0.5


def read_first(
    new: Sequence[Concept],
    item_ids: frozenset[str],
    graph: ConceptGraph,
    reader: ReaderState,
    now: datetime,
) -> tuple[str, ...]:
    """Prerequisites of the item's new ideas that are new to the reader too and that the item
    doesn't name itself; deduped, most basic first, at most READ_FIRST_MAX."""
    found: dict[str, Concept] = {}
    for c in new:
        for pre in graph.prerequisites(c.id):
            if pre.id not in item_ids and pre.id not in found and is_new(pre, reader, now):
                found[pre.id] = pre
    ordered = sorted(found.values(), key=lambda p: (p.base_difficulty, p.label))
    return tuple(p.label for p in ordered[:READ_FIRST_MAX])


def readiness_level(named: int, new: int, first: Sequence[str]) -> Readiness | None:
    if not named:
        return None  # nothing named: we know nothing about this item
    if not new:
        return "familiar"
    if first or new > READY_MAX:
        return "stretch"
    return "ready"


def why(topic: str, new: Sequence[str], goal: str | None) -> str:
    parts = [BY_ID[topic].label]
    if new:
        parts.append(f"{len(new)} idea{'s' if len(new) != 1 else ''} new to you")
    if goal:
        parts.append(f"helps your goal: {goal}")
    return " · ".join(parts)


def key_ideas(
    doc: ContentDoc, graph: ConceptGraph, k: int = READY_MAX
) -> tuple[tuple[Concept, ...], frozenset[str]]:
    """A stored article's k most salient linked ideas in the served graph (one per concept, its
    highest salience; ties by first appearance), and every idea it links. Pure."""
    best: dict[str, tuple[float, int]] = {}
    for i, d in enumerate(doc.demands):
        if d.target_id is None or graph.get(d.target_id) is None:
            continue
        seen = best.get(d.target_id)
        if seen is None or d.salience > seen[0]:
            best[d.target_id] = (d.salience, seen[1] if seen else i)
    order = sorted(best, key=lambda cid: (-best[cid][0], best[cid][1]))
    return tuple(graph.get(cid) for cid in order[:k]), frozenset(best)  # type: ignore[misc]


def attach_ideas(
    candidates: Sequence[FeedCandidate], docs: Mapping[str, ContentDoc], graph: ConceptGraph,
    k: int = READY_MAX,
) -> list[FeedCandidate]:  # fmt: skip
    """Decision 65: an article row whose URL is a stored public library article (content id =
    `url_hash` of the result's URL, corpus only: a reader's own pages stay theirs) carries its
    key ideas. Videos, podcasts and unstored or unlinked articles are returned unchanged."""
    out = []
    for c in candidates:
        doc = docs.get(url_hash(c.result.url)) if c.result.format == "article" else None
        if doc is not None and is_corpus(doc):
            ideas, covered = key_ideas(doc, graph, k)
            if ideas:
                c = replace(c, ideas=ideas, covered=covered)
        out.append(c)
    return out


def rank(
    candidates: Sequence[FeedCandidate], reader: FeedReader, now: datetime, graph: ConceptGraph
) -> list[RankedItem]:
    """The score uses the title + snippet concepts; what the row shows (new ideas, readiness,
    read-first) uses the article's key ideas when it has them (decision 65)."""
    top = max((reader.interest.get(c.topic, 0.0) for c in candidates), default=0.0) or 1.0
    out = []
    for c in candidates:
        titled = [x for x in c.concepts if is_new(x, reader.state, now)]
        shown_from = c.ideas or c.concepts
        fresh = [x for x in shown_from if is_new(x, reader.state, now)] if c.ideas else titled
        new = tuple(x.label for x in fresh)
        covered = frozenset(x.id for x in c.concepts) | c.covered
        first = read_first(fresh, covered, graph, reader.state, now)
        goal = next((reader.goal_targets[x.id] for x in c.concepts if x.id in reader.goal_targets),
                    None)  # fmt: skip
        interest = (reader.interest.get(c.topic, 0.0) or top) / top
        affinity = format_affinity(
            c.result.format, reader.prior, reader.stats.get(c.result.format, FormatStats()),
            duration_s=c.result.duration_or_read_time,
        )  # fmt: skip
        score = (
            interest
            * affinity
            * readiness(len(titled))
            * (GOAL_BOOST if goal else 1.0)
            * freshness(c.result.published_at, now)
        )
        level = readiness_level(len(shown_from), len(new), first)
        basis: ReadinessBasis = "article" if c.ideas else "title"
        out.append(RankedItem(c, round(score, 4), new, goal, why(c.topic, new, goal), level, first,
                              basis))  # fmt: skip
    return out


SideOf = Callable[[FeedCandidate], str | None]  # "local" | "global" | None (not offered)


def article_split(
    pools: Sequence[tuple[int, int]], quota: int | Sequence[int], share: float
) -> list[tuple[int, int]]:
    """Decision 50's mix. Per topic (local available, global available) → (local, global)
    article picks: each topic fills min(quota, supply) slots (`quota` per topic, or one for
    all); over all slots the local count is round(share × slots) when supply allows, a short
    side backfilled from the other. Locals are handed out round-robin in topic order. Pure."""
    quotas = [quota] * len(pools) if isinstance(quota, int) else list(quota)
    slots = [min(q, loc + glo) for q, (loc, glo) in zip(quotas, pools, strict=True)]
    lo = [max(0, s - glo) for s, (_, glo) in zip(slots, pools, strict=True)]
    hi = [min(loc, s) for s, (loc, _) in zip(slots, pools, strict=True)]
    target = min(max(int(share * sum(slots) + 0.5), sum(lo)), sum(hi))
    local, extra = list(lo), target - sum(lo)
    while extra > 0:
        for i in range(len(pools)):
            if extra > 0 and local[i] < hi[i]:
                local[i] += 1
                extra -= 1
    return [(n, s - n) for n, s in zip(local, slots, strict=True)]


def _best(pool: Iterable[RankedItem]) -> list[RankedItem]:
    return sorted(pool, key=lambda r: (-r.score, r.candidate.result.url))


def _interleave(per_topic: Sequence[Sequence[RankedItem]]) -> list[RankedItem]:
    out: list[RankedItem] = []
    for rank_i in range(max((len(p) for p in per_topic), default=0)):
        layer = [p[rank_i] for p in per_topic if rank_i < len(p)]
        out.extend(sorted(layer, key=lambda r: -r.score))
    return out[:MAX_ITEMS]


def select(
    ranked: Sequence[RankedItem], topics: Sequence[str], side: SideOf | None = None,
    share: float = 0.6, quotas: Mapping[Format, int] = QUOTAS,
) -> list[RankedItem]:  # fmt: skip
    """Per topic: up to 3 articles, 2 videos, 1 podcast (best first, one per URL; a URL filed
    under two topics belongs to the earlier one); then the topics' picks interleaved by score,
    at most 24. With `side`, articles are mixed local/global per `article_split` (articles not
    offered to this reader are dropped); videos and podcasts are outside the mix.

    The mix is sized over the slots that survive the 24-item cut: a first pass (articles best
    first, sides ignored) fixes how many articles, videos and podcasts each topic keeps after
    the cut; the split then fills exactly those article slots, so the cut can't skew it."""
    seen: set[str] = set()
    pools: list[dict[str, list[RankedItem]]] = []
    for topic in topics:
        by_kind: dict[str, list[RankedItem]] = {}
        for r in _best(r for r in ranked if r.candidate.topic == topic):
            url, fmt = r.candidate.result.url, r.candidate.result.format
            if url in seen:
                continue
            kind: str = fmt
            if fmt == "article" and side is not None:
                where = side(r.candidate)
                if where is None:
                    continue
                kind = f"article:{where}"
            seen.add(url)
            by_kind.setdefault(kind, []).append(r)
        pools.append(by_kind)

    def articles(p: dict[str, list[RankedItem]]) -> list[RankedItem]:
        return _best([*p.get("article", []), *p.get("article:local", []),
                      *p.get("article:global", [])])  # fmt: skip

    first = [
        _best(articles(p)[: quotas["article"]]
              + [r for f in ("video", "podcast") for r in p.get(f, [])[: quotas[f]]])
        for p in pools
    ]  # fmt: skip
    kept = {id(r) for r in _interleave(first)}
    keep = [
        {f: sum(id(r) in kept and r.candidate.result.format == f for r in picks) for f in quotas}
        for picks in first
    ]
    if side is None:
        return _interleave([[r for r in picks if id(r) in kept] for picks in first])
    split = article_split(
        [(len(p.get("article:local", [])), len(p.get("article:global", []))) for p in pools],
        [k["article"] for k in keep],
        share,
    )
    per_topic = [
        _best(p.get("article:local", [])[:n_local] + p.get("article:global", [])[:n_global]
              + [r for f in ("video", "podcast") for r in p.get(f, [])[: k[f]]])
        for p, (n_local, n_global), k in zip(pools, split, keep, strict=True)
    ]  # fmt: skip
    return _interleave(per_topic)


FORMAT_ORDER: tuple[str, ...] = ("article", "video", "podcast")


def onboarding_targets(formats: Sequence[str], limit: int) -> tuple[list[str], dict[str, int]]:
    """Decision 69 G: every format not chosen gets 1 card; the chosen ones (articles when none)
    share the rest equally, the remainder in FORMAT_ORDER. Article + podcast of 9 → 4 / 4 / 1."""
    chosen = [f for f in FORMAT_ORDER if f in formats] or ["article"]
    others = [f for f in FORMAT_ORDER if f not in chosen]
    base, extra = divmod(max(0, limit - len(others)), len(chosen))
    targets = {f: base + (1 if i < extra else 0) for i, f in enumerate(chosen)}
    return chosen, targets | dict.fromkeys(others, 1)


def onboarding_mix(
    groups: Sequence[Sequence[FeedCandidate]], now: datetime, limit: int,
    formats: Sequence[str] = (), served: Sequence[str] = (),
    key: Callable[[FeedCandidate], str] = lambda c: c.result.url, pending: bool = False,
) -> list[FeedCandidate]:  # fmt: skip
    """Onboarding's screen 2 (decisions 41, 68 F4, 69 G): one group per chosen topic or concept,
    in the reader's order. Within a group the reader's chosen formats first (articles when none),
    then fresher (ties by URL); groups interleaved so every one with results gets a card before
    any gets a second; one per URL. Items already `served` (by `key`) keep their slots, in served
    order, so a later poll never pushes out a card the reader may have answered. Then each format
    up to its target (`onboarding_targets`: the chosen formats share the cards equally, every
    other format gets 1), a chosen format short of results made up by the other chosen ones first.
    While searches are `pending`, a format short of its target keeps its slots free for a later
    poll. New cards take turns by chosen format (topics interleaved within each), the other
    formats after. Pure."""
    chosen, targets = onboarding_targets(formats, limit)

    def rank_in_group(c: FeedCandidate) -> tuple[bool, float, str]:
        return c.result.format not in chosen, -freshness(c.result.published_at, now), c.result.url

    ordered = [sorted(g, key=rank_in_group) for g in groups]
    pool: list[FeedCandidate] = []
    seen: set[str] = set()
    for layer in range(max((len(g) for g in ordered), default=0)):
        for g in ordered:
            if layer < len(g) and g[layer].result.url not in seen:
                seen.add(g[layer].result.url)
                pool.append(g[layer])
    by_key = {key(c): c for c in pool}
    out = [by_key[k] for k in served if k in by_key][:limit]
    kept = len(out)
    taken = {id(c) for c in out}
    for fmt in [*chosen, *(f for f in FORMAT_ORDER if f not in chosen)]:
        have = sum(c.result.format == fmt for c in out)
        for c in pool:
            if have >= targets[fmt] or len(out) >= limit:
                break
            if id(c) not in taken and c.result.format == fmt:
                out.append(c)
                taken.add(id(c))
                have += 1
    unmet = sum(max(0, t - sum(c.result.format == f for c in out)) for f, t in targets.items())
    room = max(0, limit - len(out) - (unmet if pending else 0))
    position = {id(c): i for i, c in enumerate(pool)}
    spare = sorted((c for c in pool if id(c) not in taken),
                   key=lambda c: (c.result.format not in chosen, position[id(c)]))  # fmt: skip
    return out[:kept] + _take_turns([*out[kept:], *spare[:room]], chosen, position)


def _take_turns(
    cards: Sequence[FeedCandidate], chosen: Sequence[str], position: Mapping[int, int]
) -> list[FeedCandidate]:
    """The chosen formats in turn (each in pool order), then the other formats in pool order."""
    by_fmt = {f: sorted((c for c in cards if c.result.format == f), key=lambda c: position[id(c)])
              for f in chosen}  # fmt: skip
    turns: list[FeedCandidate] = []
    for layer in range(max((len(v) for v in by_fmt.values()), default=0)):
        turns += [v[layer] for v in by_fmt.values() if layer < len(v)]
    rest = sorted(
        (c for c in cards if c.result.format not in chosen), key=lambda c: position[id(c)]
    )
    return turns + rest
