import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { api } from "../../lib/api";
import { domainLabel } from "../../lib/format";
import { layout, mapSize, type LayoutNode } from "../../lib/mapLayout";
import type { PersonaKey } from "../../lib/personas";
import { profileApi, type Band, type Domain, type OverviewNode } from "../../lib/profileApi";
import { BAND_LABEL, evidenceText } from "../../lib/profileFormat";
import { Segmented } from "../Segmented";

type View = "map" | "list";
type Scope = { kind: "all" } | { kind: "domain"; domain: Domain } | { kind: "goal"; id: string; label: string };

/** One node shape for all three sources (overview, a domain's subgraph, a goal's targets). */
interface MapNode extends Omit<OverviewNode, "definition"> {
  definition: string | null;
}

interface Props {
  persona: PersonaKey | null;
  domains: Domain[];
  initial?: Domain;
  /** Changes when anything else on the page changed the model (an applied or undone edit). */
  refreshKey: number;
  onChanged: () => void;
  /** A learning goal to show instead of the overview (M7.5 §C.5); null shows the overview. */
  goal?: { id: string; label: string } | null;
  onClearGoal?: () => void;
  goalTargets?: ReadonlySet<string>;
}

const NO_TARGETS: ReadonlySet<string> = new Set();
const NARROW = "(max-width: 639px)";
const BESIDE = "(min-width: 961px)"; // the inspector sits beside the map (profile.css)

function bandText(n: MapNode): string {
  if (n.ready) return "ready to learn";
  return BAND_LABEL[n.band].toLowerCase();
}

function ariaFor(n: MapNode): string {
  return [n.label, bandText(n), n.goal ? "in a goal" : ""].filter(Boolean).join(", ");
}

/**
 * The knowledge map (Design pass C7, DESIGN §15.1): an overview of every topic first ("You" in
 * the middle, solid dots for what we think you know, rings for what you're ready to learn,
 * dashed rings for goal targets), then a topic or a goal on its own. One Tab stop: arrow keys
 * move between nodes, Enter opens the inspector. The list view shows the same nodes as text.
 */
export function KnowledgeMap({ persona, domains, refreshKey, onChanged, goal = null, onClearGoal, goalTargets = NO_TARGETS }: Props) {
  const narrow = typeof window !== "undefined" && window.matchMedia(NARROW).matches;
  const [scope, setScope] = useState<Scope>({ kind: "all" });
  const [view, setView] = useState<View>(narrow ? "list" : "map");
  const [nodes, setNodes] = useState<MapNode[] | null>(null);
  const [edges, setEdges] = useState<{ from: string; to: string }[]>([]);
  const [shown, setShown] = useState<Domain[]>([]);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  const effective: Scope = goal ? { kind: "goal", id: goal.id, label: goal.label } : scope;
  const scopeKey = effective.kind === "all" ? "all" : effective.kind === "domain" ? `d:${effective.domain}` : `g:${effective.id}`;

  useEffect(() => {
    const ctrl = new AbortController();
    setFailed(false);
    const load = async () => {
      if (effective.kind === "all") {
        const o = await profileApi.overview(persona, ctrl.signal);
        setNodes(o.nodes);
        setEdges(o.edges);
        setShown(o.domains);
        return;
      }
      const g =
        effective.kind === "goal"
          ? await profileApi.goalGraph(effective.id, ctrl.signal)
          : await profileApi.graph(persona, effective.domain, "", ctrl.signal);
      const top = Math.max(1, ...g.nodes.map((n) => n.evidence_count));
      setNodes(
        g.nodes.map((n) => ({
          id: n.id, label: n.label, domain: n.domain, band: n.band, ready: false,
          goal: goalTargets.has(n.id), weight: Math.min(1, 0.35 + n.evidence_count / top),
          definition: null, recent: n.recent, rose_this_week: false,
        })),  // prettier-ignore
      );
      setEdges(g.edges);
      setShown([...new Set(g.nodes.map((n) => n.domain))]);
    };
    load().catch(() => !ctrl.signal.aborted && setFailed(true));
    return () => ctrl.abort();
    // goalTargets only flags nodes; a new Set each render must not refetch.
  }, [persona, scopeKey, version, refreshKey]);

  const current = nodes?.find((n) => n.id === selected) ?? null;
  const correct = async (n: MapNode, known: boolean) => {
    await api.correct(n.id, known, persona);
    setVersion((v) => v + 1);
    onChanged();
  };

  return (
    <section className="kmap" aria-labelledby="kmap-title">
      <div className="kmap__head">
        <div>
          <h2 id="kmap-title" className="kmap__title">
            Your knowledge map
          </h2>
          <p className="kmap__sub">Solid dots are ideas we think you know. Rings are what you're ready to learn next.</p>
        </div>
        <Segmented
          label="View"
          options={[
            { key: "map" as View, label: "Map" },
            { key: "list" as View, label: "List" },
          ]}
          value={view}
          onChange={setView}
        />
      </div>
      <div className="kmap__scopes" role="group" aria-label="Show">
        {goal ? (
          <p className="kmap__goal">
            Goal: <strong>{goal.label}</strong>
            <button type="button" className="btn btn--sm" onClick={onClearGoal}>
              Back to all topics
            </button>
          </p>
        ) : (
          <>
            <button type="button" className="filter" aria-pressed={scope.kind === "all"} onClick={() => setScope({ kind: "all" })}>
              All topics
            </button>
            {domains.map((d) => (
              <button
                key={d}
                type="button"
                className="filter"
                aria-pressed={scope.kind === "domain" && scope.domain === d}
                onClick={() => setScope({ kind: "domain", domain: d })}
              >
                {domainLabel(d)}
              </button>
            ))}
          </>
        )}
      </div>
      <Legend scoped={goal != null || scope.kind === "domain"} />
      {failed && <p className="profile__note" role="status">The map didn't load. Try again in a moment.</p>}
      {nodes && nodes.length === 0 && <p className="profile__note">Read a few articles and your map fills in.</p>}
      {nodes && nodes.length > 0 && (
        <div className="kmap__grid">
          {view === "map" ? (
            <MapSvg
              nodes={nodes}
              edges={edges}
              domains={shown}
              selected={selected}
              onSelect={setSelected}
              onDomain={goal ? undefined : (d) => setScope({ kind: "domain", domain: d })}
            />
          ) : (
            <NodeList nodes={nodes} domains={shown} selected={selected} onSelect={setSelected} />
          )}
          <Inspector node={current} onCorrect={correct} />
        </div>
      )}
    </section>
  );
}

/** `scoped`: a topic's or a goal's view, which also draws ideas with nothing recorded yet. */
export function Legend({ scoped }: { scoped: boolean }) {
  return (
    <ul className="kmap__legend" aria-label="Legend">
      {scoped && <li><span className="lg lg--none" aria-hidden="true" /> Nothing recorded yet</li>}
      <li><span className="lg lg--ready" aria-hidden="true" /> Ready to learn</li>
      <li><span className="lg lg--heard" aria-hidden="true" /> Heard of</li>
      <li><span className="lg lg--understands" aria-hidden="true" /> Understands</li>
      <li><span className="lg lg--explain" aria-hidden="true" /> Can explain</li>
      <li><span className="lg lg--goal" aria-hidden="true" /> In a goal</li>
    </ul>
  );  // prettier-ignore
}

function rankWithin(nodes: MapNode[]): LayoutNode[] {
  const seen = new Map<string, number>();
  return [...nodes]
    .sort((a, b) => a.domain.localeCompare(b.domain) || Number(a.ready) - Number(b.ready) || b.weight - a.weight || a.id.localeCompare(b.id))
    .map((n) => {
      const r = seen.get(n.domain) ?? 0;
      seen.set(n.domain, r + 1);
      return { id: n.id, label: n.label, domain: n.domain, weight: n.weight, rank: r };
    });
}

function MapSvg({
  nodes, edges, domains, selected, onSelect, onDomain,
}: {
  nodes: MapNode[];
  edges: { from: string; to: string }[];
  domains: Domain[];
  selected: string | null;
  onSelect: (id: string) => void;
  onDomain?: (d: Domain) => void;
}) {  // prettier-ignore
  // Wide layout (decision 45): beside the inspector the map is laid out for the box it sits in.
  // Measured before the first paint, so it never draws at one size and jumps to another. Stacked
  // (960px and under, where the canvas has a fixed height) and in a box under 800px it keeps the
  // fixed canvas, scaled into the box by CSS as before.
  const canvas = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState(() => mapSize(0));
  useLayoutEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const measure = () => {
      const next = mapSize(window.matchMedia(BESIDE).matches ? el.clientWidth : 0);
      setSize((now) => (now.width === next.width && now.height === next.height ? now : next));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const exact = size.width > mapSize(0).width;
  const placed = useMemo(() => layout(rankWithin(nodes), domains, size.width, size.height), [nodes, domains, size]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const order = useMemo(() => [...placed.nodes].sort((a, b) => a.domain.localeCompare(b.domain) || a.y - b.y || a.x - b.x), [placed]);
  const [focus, setFocus] = useState<string | null>(order[0]?.id ?? null);
  const refs = useRef<Record<string, SVGGElement | null>>({});
  const pos = useMemo(() => new Map(placed.nodes.map((p) => [p.id, p])), [placed]);

  const onKey = (e: KeyboardEvent<SVGGElement>, id: string) => {
    const i = order.findIndex((p) => p.id === id);
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(id);
      return;
    }
    if (!step && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    const next = e.key === "Home" ? order[0] : e.key === "End" ? order[order.length - 1] : order[(i + step + order.length) % order.length];
    if (!next) return;
    setFocus(next.id);
    refs.current[next.id]?.focus();
  };

  return (
    <div className="kmap__canvas" ref={canvas} data-fit={exact ? "exact" : "scale"}>
      <svg viewBox={`0 0 ${size.width} ${size.height}`} width={exact ? size.width : undefined} height={exact ? size.height : undefined} role="group" aria-label={`Knowledge map: ${nodes.length} ideas across ${domains.length} topics. Arrow keys move between ideas; Enter shows one.`}>
        {placed.center &&
          placed.clusters.map((c) => (
            <line key={`spoke-${c.domain}`} x1={placed.center!.x} y1={placed.center!.y} x2={c.x} y2={c.y} className="kmap__spoke" />
          ))}
        {edges.map((e) => {
          const a = pos.get(e.from);
          const b = pos.get(e.to);
          if (!a || !b) return null;
          const cross = a.domain !== b.domain;
          return cross ? (
            <path key={`${e.from}-${e.to}`} d={`M${a.x},${a.y} Q${(a.x + b.x) / 2},${(a.y + b.y) / 2 - 30} ${b.x},${b.y}`} className="kmap__bridge" />
          ) : (
            <line key={`${e.from}-${e.to}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="kmap__edge" />
          );
        })}
        {placed.center && (
          <g aria-hidden="true">
            <circle cx={placed.center.x} cy={placed.center.y} r={22} className="kmap__you" />
            <text x={placed.center.x} y={placed.center.y + 4} textAnchor="middle" className="kmap__you-text">
              You
            </text>
          </g>
        )}
        {placed.nodes.map((p) => {
          const n = byId.get(p.id);
          if (!n) return null;
          return (
            <g
              key={p.id}
              ref={(el) => {
                refs.current[p.id] = el;
              }}
              role="button"
              tabIndex={(focus ?? order[0]?.id) === p.id ? 0 : -1}
              aria-label={ariaFor(n)}
              aria-pressed={selected === p.id}
              className={`kmap__node${n.rose_this_week ? " kmap__node--new" : ""}${selected === p.id ? " is-selected" : ""}`}
              data-band={n.band}
              data-ready={n.ready || undefined}
              style={{ transformOrigin: `${p.x}px ${p.y}px` }}
              onClick={() => {
                setFocus(p.id);
                onSelect(p.id);
              }}
              onFocus={() => setFocus(p.id)}
              onKeyDown={(e) => onKey(e, p.id)}
            >
              {n.goal && <circle cx={p.x} cy={p.y} r={p.r + 5} className="kmap__goal-ring" />}
              {selected === p.id && <circle cx={p.x} cy={p.y} r={p.r + 9} className="kmap__sel" />}
              <circle cx={p.x} cy={p.y} r={p.r} className="kmap__dot" />
              {n.band === "can explain" && !n.ready && <circle cx={p.x} cy={p.y} r={p.r + 3} className="kmap__explain-ring" />}
              {p.showLabel && (
                <text x={p.x} y={p.y + p.r + 14} textAnchor="middle" className="kmap__label">
                  {p.label}
                </text>
              )}
              <title>{ariaFor(n)}</title>
            </g>
          );
        })}
        {placed.clusters.map((c) =>
          onDomain ? (
            <text
              key={`cl-${c.domain}`}
              x={c.x}
              y={c.labelY}
              textAnchor="middle"
              className="kmap__cluster kmap__cluster--link"
              aria-hidden="true"
              onClick={() => onDomain(c.domain as Domain)}
            >
              {domainLabel(c.domain)}
            </text>
          ) : (
            <text key={`cl-${c.domain}`} x={c.x} y={c.labelY} textAnchor="middle" className="kmap__cluster" aria-hidden="true">
              {domainLabel(c.domain)}
            </text>
          ),
        )}
      </svg>
    </div>
  );
}

function NodeList({ nodes, domains, selected, onSelect }: { nodes: MapNode[]; domains: Domain[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <div className="clist">
      {domains.map((d) => (
        <section key={d} className="clist__level" aria-labelledby={`clist-${d}`}>
          <h3 id={`clist-${d}`} className="clist__h">
            {domainLabel(d)}
          </h3>
          <ul className="clist__items">
            {nodes
              .filter((n) => n.domain === d)
              .sort((a, b) => Number(a.ready) - Number(b.ready) || a.label.localeCompare(b.label))
              .map((n) => (
                <li key={n.id}>
                  <button type="button" className="clist__item" data-band={n.band} data-ready={n.ready || undefined}
                    aria-pressed={selected === n.id} onClick={() => onSelect(n.id)}>
                    <span className="lg" data-kind={n.ready ? "ready" : n.band} aria-hidden="true" />
                    <span className="clist__label">{n.label}</span>
                    {n.goal && <span className="clist__goal">Goal</span>}
                    <span className="clist__band">{n.ready ? "Ready to learn" : BAND_LABEL[n.band as Band]}</span>
                  </button>
                </li>
              ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** Why a node with no recent evidence is drawn (decision 69 A: the map never shows a guess). */
export function inspectorNote(node: Pick<MapNode, "ready" | "band" | "domain">): string {
  if (node.ready) return "You know what it builds on, so it's next.";
  if (node.band === "unaware") return "Nothing recorded yet: read about it, or tell us below.";
  return `Set from your profile, not from reading yet, in ${domainLabel(node.domain)}.`;
}

function Inspector({ node, onCorrect }: { node: MapNode | null; onCorrect: (n: MapNode, known: boolean) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!node)
    return (
      <div className="inspect" aria-live="polite">
        <p className="profile__note">Pick an idea on the map to see why we think so, and correct us.</p>
      </div>
    );
  const correct = async (known: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await onCorrect(node, known);
    } catch {
      setError("That didn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="inspect" role="group" aria-live="polite" aria-labelledby="inspect-title">
      <h3 id="inspect-title" className="inspect__title">
        {node.label}
      </h3>
      <p className="inspect__meta">
        {domainLabel(node.domain)}, {bandText(node)}
        {node.goal ? ", part of a goal" : ""}
      </p>
      {node.definition && <p className="inspect__def">{node.definition}</p>}
      <h4 className="inspect__h">Why we think so</h4>
      {node.recent.length > 0 ? (
        <ul className="inspect__ev">
          {node.recent.map((e) => (
            <li key={`${e.type}-${e.at}`}>{evidenceText(e.type, e.at)}</li>
          ))}
        </ul>
      ) : (
        <p className="profile__note">{inspectorNote(node)}</p>
      )}
      {error && (
        <p className="welcome__error" role="alert">
          {error}
        </p>
      )}
      <div className="inspect__acts">
        <button type="button" className="btn" disabled={busy} onClick={() => void correct(true)}>
          I know this
        </button>
        <button type="button" className="btn" disabled={busy} onClick={() => void correct(false)}>
          I don't
        </button>
      </div>
    </div>
  );
}
