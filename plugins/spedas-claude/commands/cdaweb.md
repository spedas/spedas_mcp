# /spedas-agent-kit:cdaweb

Use the `spedas` MCP server for a CDAWeb (heliophysics time-series) workflow via the **unified data layer**.

1. Discover: `browse_data_sources(source_type="cdaweb", query?)`, then `load_data_source(source_type="cdaweb", source_id=...)` to enumerate dataset IDs + coverage.
2. Inspect variables before any fetch: `browse_data_parameters(source_type="cdaweb", dataset_id=...)`.
3. Fetch: `fetch_data_product(source_type="cdaweb", dataset_id=..., parameters=[...], start, stop, output_dir=...)`. Keep the time range small unless the user explicitly asked for more.
4. Report file paths, row counts, units, and the per-parameter `quality_checks`/stats (flag fill/outliers) — never paste raw arrays.

For a full analysis (turbulence spectrum, boundary/MVA, particle moments, conjunctions, …), prefer a skill — see `/spedas-agent-kit:analyze` or the `spedas-skills-index` skill.

(The legacy per-source tools `browse_observatories`/`load_observatory`/`browse_parameters`/`fetch_data` are hidden by default; the unified `source_type="cdaweb"` calls above replace them.)

Task: $ARGUMENTS
