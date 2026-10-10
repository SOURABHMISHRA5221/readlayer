import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../lib/api";
import { domainLabel } from "../../lib/format";
import type { PersonaKey } from "../../lib/personas";
import { profileApi, type Band, type Domain, type GraphNode, type Subgraph } from "../../lib/profileApi";
import { BAND_GLYPH, BAND_LABEL, evidenceText } from "../../lib/profileFormat";
import { Segmented } from "../Segmented";

type View = "map" | "list";
const NARROW = "(max-width: 639px)";

interface Props {
  persona: PersonaKey | null;
  domains: Domain[];
  initial: Domain;
  onChanged: () => void;
}

/**
 * The reader's knowledge in one domain (DESIGN §15.1 item 3): a layered map (Cytoscape + dagre,
 * loaded only when the map is shown) and the same subgraph as a keyboard-navigable list, the
 * default on phones. Either opens the node card: band, last evidence, and corrections.
 */
export function KnowledgeMap({ persona, domains, initial, onChanged }: Props) {
  const narrow = typeof window !== "undefined" && window.matchMedia(NARROW).matches;
  const [domain, setDomain] = useState<Domain>(initial);
  const [view, setView] = useState<View>(narrow ? "list" : "map");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [graph, setGraph] = useState<Subgraph | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [version, setVersion] = useState(0);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setSearch(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    const ctrl = new AbortController();
    setFailed(false);
    profileApi
      .graph(persona, domain, search, ctrl.signal)
      .then(setGraph)
      .catch(() => !ctrl.signal.aborted && setFailed(true));
    return () => ctrl.abort();
  }, [persona, domain, search, version]);

  const open = (node: GraphNode, from: HTMLElement | null) => {
    opener.current = from;
    setSelected(node);
  };

  const close = () => {
    setSelected(null);
    opener.current?.focus();
  };

  const correct = async (node: GraphNode, known: boolean) => {
    await api.correct(node.id, known, persona);
    setVersion((v) => v + 1);
    onChanged();
  };

  // Keep the open card in step with refreshed data (a correction changes the band).
  const current = selected && graph?.nodes.find((n) => n.id === selected.id);

  return (
    <section className="kmap" aria-labelledby="kmap-title">
      <div className="kmap__head">
        <h2 id="kmap-title" className="profile__h2">
          Knowledge map
        </h2>
        <div className="kmap__controls">
          <Segmented
            label="Topic"
            options={domains.map((d) => ({ key: d, label: domainLabel(d) ?? d }))}
            value={domain}
            onChange={setDomain}
          />
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
        <label className="kmap__search">
          <span className="visually-hidden">Find a concept</span>
          <input type="search" placeholder="Find a concept" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
      </div>
      <Legend />
      {failed && <p className="profile__note" role="status">The map didn't load. Try again in a moment.</p>}
      {graph && graph.nodes.length === 0 && (
        <p className="profile__note">
          {search ? `Nothing in ${domainLabel(domain)} matches “${search}”.` : "Read a few articles and your map fills in."}
        </p>
      )}
      {graph && graph.nodes.length > 0 && view === "map" && <MapCanvas graph={graph} onOpen={(n) => open(n, null)} />}
      {graph && graph.nodes.length > 0 && view === "list" && <ConceptList graph={graph} onOpen={open} />}
      {graph?.truncated && <p className="profile__note">Showing your 60 most relevant concepts here.</p>}
      {current && <NodeCard node={current} onClose={close} onCorrect={correct} />}
    </section>
  );
}

function Legend() {
  const bands = Object.keys(BAND_LABEL) as Band[];
  return (
    <ul className="kmap__legend" aria-label="Legend">
      {bands.map((b) => (
        <li key={b} data-band={b}>
          <span aria-hidden="true">{BAND_GLYPH[b]}</span> {BAND_LABEL[b]}
        </li>
      ))}
    </ul>
  );
}

function ConceptList({ graph, onOpen }: { graph: Subgraph; onOpen: (n: GraphNode, from: HTMLElement) => void }) {
  const levels = useMemo(() => {
    const by = new Map<number, GraphNode[]>();
    for (const n of graph.nodes) by.set(n.depth, [...(by.get(n.depth) ?? []), n]);
    return [...by.entries()].sort(([a], [b]) => a - b);
  }, [graph]);
  return (
    <div className="clist">
      {levels.map(([depth, nodes]) => (
        <section key={depth} className="clist__level" aria-labelledby={`clist-${depth}`}>
          <h3 id={`clist-${depth}`} className="clist__h">
            {depth === 0 ? "Foundations" : `Builds on level ${depth - 1}`}
          </h3>
          <ul className="clist__items">
            {nodes
              .slice()
              .sort((a, b) => a.label.localeCompare(b.label))
              .map((n) => (
                <li key={n.id}>
                  <button type="button" className="clist__item" data-band={n.band} onClick={(e) => onOpen(n, e.currentTarget)}>
                    <span className="clist__glyph" aria-hidden="true">
                      {BAND_GLYPH[n.band]}
                    </span>
                    <span className="clist__label">{n.label}</span>
                    <span className="clist__band">{BAND_LABEL[n.band]}</span>
                  </button>
                </li>
              ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Cytoscape + dagre, imported on first use (its own chunk). Not keyboard-operable: the list is. */
function MapCanvas({ graph, onOpen }: { graph: Subgraph; onOpen: (n: GraphNode) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  // Read at tap time, so a new callback each render doesn't rebuild the map.
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;
  useEffect(() => {
    let destroyed = false;
    let cy: { destroy(): void } | null = null;
    void (async () => {
      const [{ default: cytoscape }, { default: dagre }] = await Promise.all([
        import("cytoscape"),
        import("cytoscape-dagre"),
      ]);
      if (destroyed || !box.current) return;
      cytoscape.use(dagre);
      const accent = cssVar("--accent") || "#1f5f5b";
      const wash = cssVar("--accent-wash") || "#e6f0ee";
      const ink = cssVar("--ink") || "#1c1b19";
      const paper = cssVar("--surface") || "#fffdf9";
      const hairline = cssVar("--hairline") || "#e7e1d6";
      const fill: Record<Band, string> = { unaware: paper, "heard of": wash, understands: `${accent}99`, "can explain": accent };
      const byId = new Map(graph.nodes.map((n) => [n.id, n]));
      const instance = cytoscape({
        container: box.current,
        elements: [
          ...graph.nodes.map((n) => ({
            data: { id: n.id, label: `${BAND_GLYPH[n.band]} ${n.label}`, band: n.band },
          })),
          ...graph.edges.map((e) => ({ data: { id: `${e.from}->${e.to}`, source: e.from, target: e.to } })),
        ],
        layout: { name: "dagre", rankDir: "TB", nodeSep: 18, rankSep: 46 } as unknown as { name: string },
        minZoom: 0.4,
        maxZoom: 2.2,
        wheelSensitivity: 0.2,
        // The community types lag Cytoscape 3.30's style keys (padding, width: "label").
        style: ([
          {
            selector: "node",
            style: {
              shape: "round-rectangle",
              label: "data(label)",
              width: "label",
              height: 28,
              padding: "8px",
              "font-family": "Inter, system-ui, sans-serif",
              "font-size": 11,
              "text-valign": "center",
              "text-halign": "center",
              color: ink,
              "border-width": 1,
              "border-color": hairline,
              "background-color": paper,
            },
          },
          ...(Object.keys(fill) as Band[]).map((b) => ({
            selector: `node[band = "${b}"]`,
            style: {
              "background-color": fill[b],
              color: b === "can explain" ? paper : ink,
              "border-color": b === "unaware" ? hairline : accent,
            },
          })),
          {
            selector: "edge",
            style: {
              width: 1,
              "line-color": hairline,
              "target-arrow-color": hairline,
              "target-arrow-shape": "triangle",
              "arrow-scale": 0.7,
              "curve-style": "bezier",
            },
          },
        ] as unknown) as never,
      });
      instance.on("tap", "node", (evt: { target: { id(): string } }) => {
        const node = byId.get(evt.target.id());
        if (node) onOpenRef.current(node);
      });
      cy = instance;
      setReady(true);
    })();
    return () => {
      destroyed = true;
      cy?.destroy();
    };
  }, [graph]);
  return (
    <div className="kmap__canvas-wrap">
      <div
        ref={box}
        className="kmap__canvas"
        role="img"
        aria-label={`Map of ${graph.nodes.length} concepts and their prerequisites. Use the List view to browse them with the keyboard.`}
        aria-busy={!ready}
      />
    </div>
  );
}

function NodeCard({
  node,
  onClose,
  onCorrect,
}: {
  node: GraphNode;
  onClose: () => void;
  onCorrect: (node: GraphNode, known: boolean) => Promise<void>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
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
    <dialog ref={ref} className="ncard" aria-labelledby="ncard-title" onClose={onClose} onCancel={onClose}>
      <p className="eyebrow">{domainLabel(node.domain)}</p>
      <h3 id="ncard-title" className="ncard__title">
        {node.label}
      </h3>
      <p className="ncard__band" data-band={node.band}>
        <span aria-hidden="true">{BAND_GLYPH[node.band]}</span> {BAND_LABEL[node.band]}
      </p>
      {node.recent.length > 0 ? (
        <ul className="ncard__evidence" aria-label="Recent evidence">
          {node.recent.map((e) => (
            <li key={`${e.type}-${e.at}`}>{evidenceText(e.type, e.at)}</li>
          ))}
        </ul>
      ) : (
        <p className="profile__note">No reading activity on this yet: this is our estimate.</p>
      )}
      {error && (
        <p className="welcome__error" role="alert">
          {error}
        </p>
      )}
      <div className="ncard__actions">
        <button type="button" className="btn" disabled={busy} onClick={() => void correct(false)}>
          I don't know this
        </button>
        <button type="button" className="btn btn--primary" disabled={busy} onClick={() => void correct(true)}>
          I know this
        </button>
      </div>
      <button type="button" className="icon-btn ncard__close" aria-label="Close" onClick={() => ref.current?.close()}>
        ×
      </button>
    </dialog>
  );
}
