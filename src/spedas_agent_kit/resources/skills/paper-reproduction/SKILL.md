---
name: paper-reproduction
description: Reproduce a published heliophysics paper or figure with SPEDAS Agent Kit by turning paper evidence into a narrow data plan, artifact bundle, provenance record, and actionable Agent Kit feedback.
---

# Paper reproduction workflow

Use this skill when a researcher asks to reproduce, sanity-check, or extend a
published paper, figure, event list, or DOI using SPEDAS / PySPEDAS / Agent Kit.
The goal is not to claim a paper-quality reproduction on the first pass. The goal
is to make a **narrow, auditable researcher attempt** that produces artifacts,
records provenance, and turns every missing capability into concrete Agent Kit
feedback.

## Deliverables

Write an artifact bundle under an explicit `output_dir` containing at least:

- `REPORT.md` — citation, science question, interval/product assumptions,
  reproduction status, caveats, and Agent Kit feedback.
- `artifacts/provenance.json` — machine-readable run record using the schema
  below.
- One or more plots or small derived tables. Prefer PNG/HTML/JSON artifacts over
  pasted arrays or CDF contents.
- The script, notebook, or recipe that regenerated the artifacts.

## Workflow

1. **Intake the paper evidence.** Capture title, DOI, figure/table target, science
   question, mission(s), instrument(s), cadence, coordinate basis, and any exact
   interval from the paper or supplement. If the interval is inferred, label it as
   `candidate_interval`.
2. **Plan the data route before fetching.** Choose `source_type`, dataset/product,
   parameters/variables, time range, cache/output directory, and expected artifact
   shape. Start with `spedas_overview`, `search_spedas_data_sources`,
   `plan_spedas_observation`, or `create_spedas_analysis_bundle` when the route is
   unclear. If you bypass Agent Kit and use PySPEDAS directly, state why.
3. **Fetch narrowly.** Use the smallest interval and product set that can test the
   paper claim. Keep cache and output paths isolated per paper/iteration.
4. **Reproduce one minimum diagnostic.** Make a researcher-useful first plot or
   derived quantity before attempting the full paper. Examples: overview time
   series, `E + Ve×B` / `J·E'` proxy, `E_parallel` proxy, PSD, pitch-angle
   distribution, or particle distribution slice. Label proxy diagnostics as
   `proxy`, not paper-quality.
5. **Validate visually and numerically.** Check the artifact is non-empty, axes and
   units are labeled, spikes/features align with the target interval, and the
   provenance contains enough fields to rerun the attempt.
6. **Record Agent Kit feedback.** For every paper, write one concrete gap or
   improvement. Batch repeated gaps across several papers before opening PRs;
   avoid one issue per paper unless the bug blocks progress.

## Minimal provenance schema

This template is the human-readable copy. The canonical, machine-readable schema
ships at `spedas_agent_kit/resources/schemas/reproduction_provenance.schema.json`
(MCP resource `spedas-preset://schemas/reproduction_provenance`) and is validated
by `spedas_agent_kit.resources.provenance.validate_reproduction_provenance`, which
checks *shape only* (required keys, allowed labels, parseable increasing
`trange_utc`) and does not assert scientific reproduction quality.

Keep `provenance.json` stable enough that future tools can validate or migrate it.
Add domain-specific fields as needed, but keep these top-level keys:

```json
{
  "paper": {
    "title": "...",
    "authors": "...",
    "journal": "...",
    "year": 2026,
    "doi": "..."
  },
  "target": {
    "science_question": "...",
    "figure_or_result": "...",
    "status_label": "paper_quality | proxy | candidate_interval | partial_success"
  },
  "event_assumption": {
    "trange_utc": ["YYYY-MM-DD/hh:mm:ss", "YYYY-MM-DD/hh:mm:ss"],
    "mission": "...",
    "spacecraft": "...",
    "note": "which parts are exact vs inferred"
  },
  "data_plan": {
    "source_type": "cdaweb | pds | spice | pyspedas | mixed",
    "datasets_or_products": ["..."],
    "variables_or_parameters": ["..."],
    "output_dir": "..."
  },
  "environment": {
    "python": "...",
    "spedas_agent_kit_version_or_commit": "...",
    "cache_dir": "..."
  },
  "selected_variables": {"logical_name": "actual_loaded_name"},
  "derived_diagnostics": [
    {
      "name": "JdotEprime",
      "formula": "...",
      "units": "...",
      "quality": "proxy",
      "coordinate_assumption": "..."
    }
  ],
  "artifacts": {"overview_png": "artifacts/..."},
  "validation": {
    "visual_sanity": "pass | fail | not_checked",
    "known_caveats": ["..."]
  },
  "agent_kit_feedback": ["..."],
  "errors": [],
  "caveats": [],
  "status": "success | partial-success | failed"
}
```

## Quality labels

Use explicit labels instead of burying uncertainty in prose:

- `paper_quality` — exact paper interval, coordinate basis, calibration choices,
  and diagnostic definition are matched or intentionally documented.
- `proxy` — useful physics proxy from available variables, but not the paper's
  calibrated method.
- `candidate_interval` — interval is plausible but still needs paper/supplement
  confirmation.
- `partial_success` — data loaded and artifacts exist, but a core target failed or
  remains unverified.

## Agent Kit feedback template

Add one concise feedback item to the report and any campaign ledger:

```markdown
Agent Kit feedback: <specific missing workflow/tool/doc/schema>. Evidence: while
reproducing <paper/figure>, I had to <manual workaround>. Desired behavior: Agent
Kit should <researcher-facing capability>, preserving <provenance/caveat/gate>.
```

Good feedback names the repeated researcher pain, not just the failed command.
Examples:

- Paper → canonical interval/product scaffolding is missing.
- Derived MMS reconnection diagnostics need unit-checked provenance (`E + Ve×B`,
  `J·E'`, `E_parallel`).
- FPI distribution support variables and velocity-space slice axes need a
  researcher-facing workflow; raw tensors are not enough.

## PR sizing

For a first PR after a batch of reproductions, prefer scaffolding that helps the
next papers immediately:

- a shared skill/template;
- validation of provenance shape;
- documentation of proxy/candidate labels;
- small tests proving the skill is packaged and visible as a resource.

Do **not** overbuild the first PR with DOI resolvers, per-paper event catalogs,
LMN/curlometer physics, or distribution-slice math unless the batch evidence shows
that exact implementation is the smallest unblocker.
