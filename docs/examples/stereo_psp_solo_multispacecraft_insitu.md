# STEREO / PSP / Solar Orbiter multi-spacecraft in-situ smoke workflow

Use this example when a paper combines PSP, Solar Orbiter, STEREO, or OMNI
context but a full remote-sensing / propagation reproduction would be too broad
for a first Agent Kit run.

## First-pass data routes

- **Solar Orbiter switchbacks:** try MAG `rtn-normal` first and expect variable
  `B_RTN`; if SWA/PAS `pas-grnd-mom` is unavailable for the interval, keep a
  MAG-only artifact and record that fallback.
- **PSP + SolO radial alignment:** use `spice-conjunction-finder` for geometry,
  then make a reduced in-situ panel before attempting source mapping.
- **OMNI context:** when OMNI does not expose a ready vector, fetch scalar
  components `BX_GSE`, `BY_GSE`, and `BZ_GSE` together in one `fetch_data_product`
  call. The combined artifact uses scalar-column names `BX_GSE.1`, `BY_GSE.1`,
  and `BZ_GSE.1`; pass those exact names as `vector_cols` to coordinate/MVA/FAC
  tools and keep `coord_in="gse"` from the artifact provenance. Do not silently
  join separately fetched or different-cadence components.
- **STEREO multi-day events:** start with MAG `1min` plus PLASTIC; reserve high
  cadence such as `8hz` for short sub-intervals.

## Caveat template

> This artifact reproduces the in-situ data route and timing context. It does not
> claim full remote-sensing/J-map, Venus Express, MESSENGER, or solar-source
> mapping reproduction unless those products are explicitly loaded and documented.
