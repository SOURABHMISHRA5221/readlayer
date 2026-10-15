# Sense-labelled concepts need confirmation, plus a wrong prerequisite (decision 66)

Branch `oct16-seeding-2` (with decision 65; one review, one PR, one API deploy). Sourabh,
2026-10-15, "yes" to fixing the errors decision 65's measurement exposed. Cut-off as decision 65:
checked at 19:00 IST; if not merged then, ship decision 65 alone and propose cutting this.

## What is wrong (measured 2026-10-15, production, read only)

- **Notes in the wrong sense.** The linker accepts an exact label/alias match without the model
  (`graph/linking.alias_target`; DESIGN §2 "exact label/alias match first"). `normalize_label`
  drops parentheses, so the bare word "Pip" matches the label "Pip (finance)". The pre-ingested
  Guardian PIP-benefits article (a policy-student first-page row) has 6 demands "Pip" → Pip
  (finance); live, the newcomer and policy student see a "Pip (finance)" note, and the feed shows
  "read up on Currency pair first". The label's own parenthesis says it is one sense of an
  ambiguous word, yet that is exactly the case accepted unchecked.
- **Scale.** 386 stored docs; 92 docs (84 `fetch`, 7 `user_ingested`, 1 extension) hold 263
  demands linked to a parenthesised concept by bare text. Most parentheses are acronyms ("open
  market operation (OMO)", "cash reserve ratio (CRR)"), correct by construction. Sense labels:
  Pip (finance), Security (finance), Credit (accounting), Duration (bond), Specie (coined money),
  Intrinsic value (options), Time value (options), Monetization (economics), Base effect
  (economics), Haircut (finance), Syndicate (finance), Greeks (finance), Blockade (military),
  Ontology (information science) and similar; most sit in finance articles where the sense is
  right, a few (Pip) are wrong.
- **A wrong prerequisite.** Modding tool (technology, grown) → Utility, the patent-law term
  (prerequisite Patentability). Decision 65 shows "read up on Utility first" on a GTA 6 row.

## Changes

**L1. A sense label is never an unchecked exact match.** A concept label is *sense-labelled* when
it ends in " (x)" and x contains a lower-case letter ("Pip (finance)", "Duration (bond)"; not
"(OMO)", "(M1, M2, M3)", "401(k)" (no space), nor a parenthesis mid-label). In
`linking.alias_target`, a lookup hit on a sense-labelled concept counts only when the demand's
label or anchor itself contains the parenthetical sense ("Pip (finance)"); otherwise the demand
goes the normal way: embedding, nearest candidates, `link_confirm` on MODEL_QUALITY (which can
pick the finance sense, another concept, or none). Acronym parentheses keep exact matching.
`pending_labels` follows automatically (it uses `alias_target`). Pure, tested.

**L2. Re-link the stored docs that L1 changes** (`scripts/relink_senses.py`, new, committed):
- Scope: stored docs with a demand whose `target_id` is a sense-labelled concept reached by bare
  text (L1's rule), except the held-out docs (`eval_heldout.read_heldout`, so the reported
  precision numbers stay as measured) and `grown` demands (decision 34).
- Per doc, `link_demands` on those demands only (the doc's paragraphs, site and URL), the doc's
  other demands untouched; only `target_id` changes.
- `--dry-run` (run first): calls the models (embeddings + one `link_confirm` batch per doc; that
  is how the new links are known), prints per demand old → new (or unlinked), the doc count and
  the spend, saves the answers to a local file and writes nothing to Firestore. `--write` applies
  exactly the saved answers, with no model call, and refuses a doc whose demands changed since.
- Refuse above $1.00 estimated; production writes: ≤ 92 docs, demands only. Run after the code is
  merged and **before** the API deploy, so every instance's catalog loads the new links.

**L3. A cached explanation for another concept is a miss.** In `explain/service.serve`, a cached
restatement or Background whose stored `concept_id` differs from the span's current
`inputs.concept_id` (span mode; an entry without one is kept) is treated as missing: regenerated on
demand (within the reader's cap) and written over the same key. No deletions, no cache wipe: only
spans whose link changed ever miss.

**L4. Known-wrong prerequisite.** `("c_modding_tool", "c_utility")` added to
`graph/prereq_fixes.KNOWN_WRONG_PREREQS` (the patent-law Utility).

## Tests first

- `test_graph.py`: `alias_target` refuses "Pip" → Pip (finance), accepts "Pip (finance)", accepts
  "OMO"/"open market operations" → open market operation (OMO), accepts "401(k)"; the refused
  demand appears in `pending_labels` and reaches `plan_links` questions with the sense concept
  among candidates when similar enough; `link_demands` with a fake confirm that picks Personal
  Independence Payment links it there.
- `test_relink_senses.py`: scope selection (sense-labelled by bare text in, acronym out, held-out
  doc out, grown demand out); applying saved answers changes only those demands' `target_id`;
  refusal when the doc's demands changed since the dry run; the cost refusal.
- `test_explain_*` (nearest existing file): a cached entry with another `concept_id` regenerates
  and overwrites; the same concept or no `concept_id` is a hit.
- `test_prereq_fixes` (or `test_graph.py`): the new pair is dropped on load.

## Measurement (recorded in STATUS §34)

The dry run's full old → new list, read for sense; targets set now: every "Pip" in the PIP article
leaves Pip (finance); finance-sense links in finance articles mostly stay (each change read and
listed); no link moves to a worse sense (any that does → stop, tell Sourabh, don't tune). After
the write and deploy: the PIP article's notes per persona (no Pip (finance)), the GTA row's
read-first line (no Utility), and `feed_quality.py` again for decision 65's numbers.

## Ship

With decision 65: API pytest + ruff; `pnpm -r typecheck`. milestone-reviewer → PR → CI → merge →
`relink_senses --write` (production writes within the counts above) → `make deploy-api` on
Sourabh's yes → `make deploy-web` on his yes → live checks of both decisions.

Spend: the dry run's estimate (≤ $1.00), then $0 (the write applies saved answers). Explanation
regeneration for re-linked spans happens only when someone opens them, within normal caps.
