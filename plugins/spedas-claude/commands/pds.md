# /spedas-agent-kit:pds

Use the `spedas` MCP server for a NASA PDS Planetary Plasma Interactions workflow via the **unified data layer**.

1. Discover: `browse_data_sources(source_type="pds", query?)`, then `load_data_source(source_type="pds", source_id=...)` to enumerate dataset IDs + coverage.
2. Inspect variables before any fetch: `browse_data_parameters(source_type="pds", dataset_id=...)`.
3. Fetch: `fetch_data_product(source_type="pds", dataset_id=..., parameters=[...], start, stop, output_dir=...)`. Keep the time range small; narrow by time + parameters (PDS has no `limit` control).
4. Be explicit that some PDS datasets have metadata/label coverage gaps. Report file paths, row counts, and units — never paste raw arrays.

(The legacy per-source tools `browse_pds_missions`/`load_pds_mission`/`browse_pds_parameters`/`fetch_pds_data` are hidden by default; the unified `source_type="pds"` calls above replace them.)

Task: $ARGUMENTS
