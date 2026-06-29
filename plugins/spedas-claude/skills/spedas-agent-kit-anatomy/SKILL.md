---
name: spedas-agent-kit-anatomy
description: >
  The maintenance + navigation convention for the spedas_agent_kit repo, adapting the
  LingTai anatomy system. The codebase is mapped by a tree of ANATOMY.md files
  rooted at the repo's ANATOMY.md; this skill is the convention, those files are
  the content.

  Reach for this skill when:
    - You (a coding agent) are about to read or change spedas_agent_kit code and want
      to navigate by structure instead of grep — descend the anatomy tree from
      the repo root.
    - You are adding/changing a tool, a data source, an analysis function, or a
      skill, and need the maintenance rules (where it goes, what to update in the
      same commit, how to verify it).
    - You are writing or fixing an ANATOMY.md and need the template + citation
      discipline.

  How to use:
    1. Read this file once — you are learning the convention.
    2. Open the repo-root ANATOMY.md. Use its Components/Composition to find the
       folder whose anatomy answers your question; descend.
    3. Read the cited code (file:line). The anatomy navigates; the code is truth.
    4. If anatomy disagreed with code, fix the anatomy in the SAME commit.
       Reading and maintaining are the same act.
version: 0.1.0
---

# spedas_agent_kit anatomy — the convention & maintenance contract

The spedas_agent_kit repo is mapped by a tree of `ANATOMY.md` files (root + `src/spedas_agent_kit/`, `analysis/`, `datasources/`). This skill is the **convention**; those files are the **content**. It is the top-level maintenance guide for any coding agent touching this repo.

## What an `ANATOMY.md` is

A code-cited structural map of **one folder**, written for an agent reader, next to the code. Every structural claim points at a `file:line`. It is NOT a manual (those are the analysis skills), an API contract (tool schemas), or rationale (commit messages / PRs). If a claim can't cite a line, it doesn't belong in anatomy.

A folder earns an `ANATOMY.md` when an agent could usefully reason about it as a unit without first reading siblings. Trivial leaves don't. The repo-root anatomy is the only file with a complete child enumeration.

## The 6-section template (~80-line cap)

1. **What this is** — one paragraph naming the concept the folder embodies.
2. **Components** — files/functions/types with `file:line` citations + one-line purposes.
3. **Connections** — what calls in, what it calls out, what data flows through.
4. **Composition** — parent + subfolders (each linked to its own `ANATOMY.md`).
5. **State** — persistent state written; ephemeral state managed.
6. **Notes** — bounded rationale/gotchas not visible in code.

Citations look like `src/spedas_agent_kit/server.py:1072`. Keep them current — they drift when code moves; fixing drift is part of any edit.

## Maintenance contract (do these in the SAME commit as the code change)

- **Add/rename/move a tool** → update `src/spedas_agent_kit/ANATOMY.md` (and root if the surface count changes). New capability lands as a unified `source_type` or a **skill**, NOT a new top-level tool, unless it truly cannot be either (the consolidation goal: keep the advertised base surface small; verify the current count with `scripts/smoke_mcp_list_tools.py`).
- **Add an analysis function** → put it in `analysis/`, register it in `create_server()`, add its backend to `_ANALYSIS_REQUIRED_IMPORTS` at the **submodule** path (`server.py:55`; a package-level probe silently hides ALL analysis tools), and update `analysis/ANATOMY.md`.
- **Add a data source** → `datasources/` with a precise `require_*` guard; update `datasources/ANATOMY.md`.
- **Add a skill** → one dir under `plugins/spedas-claude/skills/`, follow the existing SKILL.md shape (When to use / Tool chain / Backend with VERIFIED contract / Procedure / Guardrails / Example), index it in `spedas-skills-index`, and reference only the unified tools.

## Non-negotiable disciplines (hard-won)

- **Verify the backend I/O contract live before authoring** a tool or skill. State whether a backend **returns an array**, **stores a tplot var** (retrieve via `get_data`; `tnames()`-listed ≠ retrievable), or **returns a dict**. This mismatch is the #1 recurring bug.
- **`render_tplot` renders one 2-D matrix per `.npz`** — one panel per file; never pack multiple panels into one multi-key npz.
- **Artifact-first:** pass `output_dir`, write bulk to disk, return paths + compact stats; never inline arrays.
- **Bake in the reliability gate** where one exists (MVA eigenvalue ratio, curlometer ∇·B/∇×B, wavelet cadence_warning, L-shell domain guard, particle `magf`).
- **Verify numerics with explicit numeric Unix-second timestamps**, never `pd.date_range().astype(str)` (it corrupts `dt`).
- **The fragile seam is facade↔backend adapters**, not dispatch — test adapter output shapes, not just that a call succeeds.

## Verify after any change

`uv run --extra dev --extra mcp --extra analysis python -m pytest -q` (full suite) · `uv run --extra mcp python scripts/smoke_mcp_list_tools.py` (advertised surface) · `python -c "import spedas_agent_kit.<module>"` (import smoke). If you changed the tool surface, confirm the count before/after.
