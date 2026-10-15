# Sense-labelled links need confirmation, plus a wrong prerequisite (decision 66)

Branch `oct16-seeding-2` (with decision 65; one review, one PR, one API deploy). Sourabh,
2026-10-15, "yes" to fixing the errors decision 65's measurement exposed.

**Scope (round 2):** the linker fix for every new link, plus a re-link of the **demo docs only**
(below). Re-linking the whole store safely needs more than today allows (concurrent growth
writes, a revert path, shared cache keys); it is deferred and recorded in STATUS §5 with the
measured counts. **Cut-off**, checked on the clock at 19:00 IST: if this is not merged by then,
the PR ships decision 65 alone (its code and docs, without this plan's commits) and this follows.

## What is wrong (measured 2026-10-15, production, read only)

- **Notes in the wrong sense.** The linker accepts an exact label/alias match without the model
  (`graph/linking.alias_target`). `normalize_label` drops parentheses, so the bare word "Pip"
  matches the label "Pip (finance)". The pre-ingested Guardian PIP-benefits article (a
  policy-student first-page row) has 6 demands "Pip" → Pip (finance); live, the newcomer and the
  policy student see a "Pip (finance)" note, and decision 65's feed line says "read up on Currency
  pair first". Aliases do the same: "short" → Short positions (alias "Short (finance)"),
  "settlement" → Trade settlement (alias "Settlement (finance)").
- **Scale.** 386 stored docs; 92 hold 263 demands linked by bare text to a concept with a
  parenthesis in its label. Most parentheses are acronyms (OMO, CRR, OEMs, RoDTEP), correct by
  construction; most sense labels sit in finance articles where the sense is right.
- **A wrong prerequisite.** Modding tool (grown; production read of `graph_growth/c_modding_tool`
  2026-10-15: prerequisites Computer program, Utility) → Utility, the patent-law term.

## Changes

**L1. A one-word sense key is never an unchecked exact match** (`graph/linking.alias_target`).
- *Sense parenthetical*: the text inside a trailing " (…)" that, after dropping a final "s", holds
  a run of 3 or more lower-case letters: "finance", "bond", "coined money" are senses; "OEMs",
  "RoDTEP", "VoiP", "FY26", "M1, M2, M3", "OMO" are not; "401(k)" (no space) has none.
- A lookup hit is refused (→ embedding + `link_confirm`, the normal path) when the matched key is
  **one word** and it came from a sense-labelled label or a sense-parenthesised alias of the hit
  concept (computed per key: the concept's label and aliases whose `normalize_label` equals the
  key), unless the demand's own label or anchor contains that sense parenthetical. Multi-word keys
  ("bond duration", "time value", "goods and services tax") stay exact matches.
- Context-type demands so refused become unlinked (they are not embedded). `pending_labels`
  follows (it uses `alias_target`).
- Untouched, recorded in STATUS §5: `graph.lookup` itself (onboarding typed phrases, goals,
  `resolve_names`, the feed's `named_concepts`, which already refuses parenthetical labels for one
  word), and growth (it merges via `link_merge`). `eval_heldout.method()` uses `alias_target`; it
  is not re-run before submission (its alias/confirmed split would shift).
- DESIGN §2 "Entity linking" gains the exception.

**L2. Re-link the demo docs** (`scripts/relink_senses.py`, new, committed).
- Docs: `warm_demo.DEMO_ARTICLES` plus the article rows of the three demo feeds' first pages (the
  16 pre-ingested ones), corpus only, held-out excluded (`app.graph.heldout.is_heldout`, checked
  against `url_hash(read_heldout())`). Demands in scope: the code decides, not a copy of it: old
  rule `alias_target(d) == d.target_id` and new rule `alias_target(d) is None`, `grown` demands out.
- Graph: `load_serving_graph`, aborting if grown concepts did not load (it otherwise swallows the
  error); the graph version is saved with the dry run.
- `--dry-run`: checks today's spend against the $8 cap; estimates before any call (questions ×
  the measured `link_confirm` cost per question) and refuses above $1.00; calls the models with
  the script's own ledgered `embed`/`confirm` (stopping if the ledger passes $1.00); prints per
  demand old → new (or unlinked), the persona diff (deterministic annotate output per demo doc ×
  persona, old links vs new, as `relink_dry_run.persona_diff` did) and the cache entries L3 would
  delete; saves everything (old and new per demand, graph version) to a local file.
- `--write`: per doc, one Firestore transaction that re-reads it, refuses if its demand ids or
  target ids differ from the dry-run snapshot or `growing_until` is in the future, and updates
  only the `demands` field (never `put` of the whole doc). `--revert` applies the saved old values
  under the same precondition. Production writes: the dry run's printed doc and demand counts.
- Run after merge and **before** the API deploy, so every instance's catalog loads the new links.

**L3. Retire the cached explanations of re-linked spans** (same script, `--write`, after L2).
Cache entries store their `span_hash` (span mode: content id, paragraph id, span text; paragraph
mode: the paragraph). For each re-linked demand, the entries with its span's hash and with its
paragraph's paragraph-mode hash are found by a query on `span_hash` and deleted. The dry run
prints the count; the deletes need **Sourabh's yes** (cache only, no user data; regenerated on
the next hover within normal caps). No serving-path change, so no miss loop on spans whose
demands disagree.

**L4. Known-wrong prerequisite.** `("c_modding_tool", "c_utility")` added to
`graph/prereq_fixes.KNOWN_WRONG_PREREQS`.

## Tests first

- `test_graph.py` (linking): refused: "Pip" → Pip (finance), "short" → Short positions (alias
  "Short (finance)"); kept: "Pip (finance)", "Goods and Services Tax" → GST, "OMO" and "open market
  operations" → open market operation (OMO), "OEMs" → original equipment manufacturers (OEMs),
  "RoDTEP", "401(k)", "bond duration" (multi-word key of Duration (bond)). The refused demand is in
  `pending_labels`; `link_demands` with a fake confirm that picks Personal Independence Payment
  links it there; a refused context-type demand ends unlinked.
- `test_relink_senses.py`: scope (sense key in, acronym out, held-out out, grown out, multi-word
  out); `--write` changes only those demands' `target_id` and only the `demands` field; refusal
  when demands changed since the dry run and when a growth claim is live; `--revert` restores;
  cost refusal before any call; the cache query deletes only matching `span_hash` entries.
- `test_prereq_fixes` (or `test_graph.py`): the new pair is dropped on load.

## Measurement (recorded in STATUS §34, with decision 65)

The dry run's old → new list, read for sense; targets set now: every "Pip" in the PIP article
leaves Pip (finance); no link moves to a worse sense (any → stop, tell Sourabh). Persona diff for
the demo docs read. After write + deploy: the PIP article's notes per persona (no Pip (finance)),
the GTA row (no "Utility"), `feed_quality.py` for decision 65's numbers, then `warm_demo` for the
demo articles whose spans were retired (count and estimate printed by the dry run; ≈ $0.01 a
card).

## Ship

With decision 65: API pytest + ruff; `pnpm -r typecheck`. milestone-reviewer → PR → CI → merge →
`relink_senses --dry-run` → `--write` (links; cache deletes on Sourabh's yes) → `make deploy-api` on
his yes → `make deploy-web` on his yes → live checks → `warm_demo`. Undo: `--revert`.

Spend: ≤ $1.00 for the dry run's model calls, then $0 for the write; re-warming as estimated.
Deferred (STATUS §5): the full-store re-link (92 docs / 263 demands by the round-1 measure).
