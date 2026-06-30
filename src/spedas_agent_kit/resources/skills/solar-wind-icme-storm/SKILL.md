---
name: solar-wind-icme-storm
description: Build artifact-first OMNI/Wind/ACE/STEREO solar-wind storm and ICME reproductions with event presets, variable alias normalization, standard overview panels, and quality caveats.
---

# Solar-wind storm and ICME workflow

Use this skill for near-Earth or heliospheric solar-wind event papers: extreme
speed streams, shocks, ICMEs, magnetic clouds, geomagnetic storms, and STEREO
in-situ event reproductions. It complements `paper-reproduction` with a standard
OMNI/Wind/ACE/STEREO data route and overview panel set.

## Good first targets

| Paper/event family | Typical starting interval | Data route | First diagnostic |
|---|---|---|---|
| Skoug et al. 2004 Halloween high-speed solar wind, DOI `10.1029/2004JA010494` | `2003-10-29/00:00:00`–`2003-10-31/00:00:00` | OMNI HRO 1-min plus Wind/ACE context when needed | speed, Bz GSM, density, temperature, dynamic pressure, SYM-H/AE |
| Liu et al. 2014 July 2012 extreme ICME, DOI `10.1038/ncomms4481` | `2012-07-23/00:00:00`–`2012-07-25/00:00:00` | STEREO-A MAG + PLASTIC | `|B|`, B components, speed, density, temperature |
| Rouillard et al. 2009 Sun-to-Venus storm, DOI `10.1029/2008JA014034` | `2007-11-14/00:00:00`–`2007-11-21/00:00:00` | STEREO-A/B MAG `1min` + PLASTIC first; SECCHI/J-map and VEX/MESSENGER only as caveated context | multi-spacecraft in-situ overview, data-volume guardrails, remote-sensing/non-SPEDAS caveats |
| Bastille Day / other Wind-ACE clouds | paper interval or event-list interval | Wind/ACE MFI/SWE plus OMNI for geomagnetic response | shock/sheath/cloud overview with source-specific timing caveats |

Treat event windows as starting points. Exact shock, sheath, ejecta, or magnetic
cloud boundaries require paper/event-list confirmation.

## Workflow

1. **Use paper reproduction as the outer contract.** For DOI/figure requests, load
   `paper-reproduction`; use this skill for event-product choices and standard
   panels.
2. **Pick the event frame.** Decide whether the reproduction is near-Earth
   propagated context (usually OMNI), source-spacecraft context (Wind/ACE), or
   heliospheric context (STEREO/PSP/Solar Orbiter). Record this choice.
3. **Normalize common variable aliases.** Examples seen in real reproductions:
   - OMNI geomagnetic indices: `AE_INDEX`, `AL_INDEX`, `AU_INDEX`, `SYM_H`;
   - OMNI solar wind: `flow_speed`, `proton_density`, `T`, `Pressure`, `BZ_GSM`;
   - STEREO/PLASTIC: `proton_bulk_speed`, `proton_number_density`,
     `proton_temperature`;
   - STEREO/MAG may expose generic `BFIELD`; record coordinate/component metadata
     or keep labels generic if metadata is not surfaced.
4. **Make a standard overview first.** Preferred panels:
   - solar-wind speed;
   - B components or Bz GSM and `|B|`;
   - proton density;
   - proton temperature or thermal speed;
   - dynamic pressure when available;
   - geomagnetic response (`SYM_H`, AE/AL/AU) for near-Earth events.
5. **Label quality.** Use `paper_quality` only when timing, source, propagation,
   coordinate basis, and boundary definitions match the paper. Otherwise use
   `candidate_interval` or `proxy`.
6. **Record reusable event feedback.** If manual code was needed, name the missing
   preset/alias/overview capability rather than only the single paper.

## Batch-004 multi-spacecraft data-route guardrails

Batch 004 extended this skill from Earth/ICME overviews into STEREO + PSP/SolO
reduced in-situ passes. Keep these data-route lessons resident:

- **OMNI scalar components:** OMNI HRO may expose vector fields as separate
  scalar variables such as `BX_GSE`, `BY_GSE`, and `BZ_GSE` rather than one vector
  array. Fetch the three components together in one `fetch_data_product(...,
  parameters=["BX_GSE", "BY_GSE", "BZ_GSE"])` call so Agent Kit writes one
  time-aligned artifact; scalar CDF columns are named with a `.1` suffix
  (`BX_GSE.1`, `BY_GSE.1`, `BZ_GSE.1`). Pass those exact names to vector tools as
  `vector_cols=["BX_GSE.1", "BY_GSE.1", "BZ_GSE.1"]`, preserve `coord_in="gse"`
  from the returned `source_frame`/provenance, and record the original component
  names before plotting `|B|` or vector panels. Do not separately fetch and
  silently join different-cadence components.
- **STEREO cadence/data volume:** for multi-day events such as Rouillard et al.
  2009 (`10.1029/2008JA014034`), avoid starting with high-rate MAG (`8hz`) over
  a week-long window. Use STEREO MAG `1min` plus PLASTIC for the first artifact,
  then escalate cadence only for narrow sub-intervals.
- **Remote-sensing and non-SPEDAS context:** SECCHI/J-map, Venus Express, and
  MESSENGER context may be essential to the paper but are not automatically
  reproduced by a reduced SPEDAS in-situ panel. State this as a source-boundary
  caveat instead of implying full Sun-to-planet reproduction.
- **PSP/SolO radial alignment:** when a storm/stream-interaction paper depends on
  spacecraft geometry, cross-load `spice-conjunction-finder` for conjunction or
  radial-alignment context, then keep this skill responsible for the in-situ
  overview panels and timing/provenance.

## Batch-007 heliospheric ICME / SEP guardrails

Batch 007 extended the solar-wind event workflow from single-event ICME overviews
into multi-spacecraft STEREO/Wind/ACE and reduced SEP reproductions:

- **STEREO A/B first pass:** for 2007 May and 2010 August multi-day events, start
  with STEREO MAG `1min` plus PLASTIC proton moments. Record spacecraft (`sta` /
  `stb`), coordinate labels, cadence, and whether MAG appears as generic
  `BFIELD` before comparing rotations or `|B|`.
- **Time-shifted comparisons are manual unless documented:** a panel aligning
  STEREO, Wind, ACE, and OMNI is a timing-context artifact, not a propagation or
  boundary-fit result. Record whether boundaries are not identified,
  event-list-supplied, or paper-supplied.
- **SEP profiles are reduced proxies:** STEREO SEPT/LET/HET, ACE, and Wind
  particle channels require telescope, species, energy band, units, and sector
  metadata before onset, fluence, anisotropy, or longitudinal-spread claims. If
  those choices are not reproduced, label the output `reduced_sep_proxy`.
- **HI/J-map scope boundary:** CME-CME interaction papers may depend on SECCHI/HI
  J-maps or arrival-time fitting. A SPEDAS in-situ overview can support the event
  route, but it is not a remote-sensing reproduction unless those products are
  explicitly loaded and cited.
- **Use the example doc:** `docs/examples/stereo_icme_multispacecraft.md` carries
  Batch 007 seed rows and a provenance snippet for these cases.

## Batch-009 storm/operational-context cross-reference

Batch 009 revisited Halloween 2003 and Bastille Day 2000 through ENA-emission
and Brazilian-anomaly precipitation papers, but only loaded OMNI/Kyoto storm
context. Do not add duplicate seed rows for those intervals and do not claim ENA
imaging, precipitation, GIC, TEC, or ground-detector reproduction from OMNI/Kyoto
overlays. Route GOES XRS / storm-index context to `overview-geomagnetic-indices`
and keep XRS labeled as operational flare context unless a calibrated paper recipe
is present.

## Caveats to state in the report

- OMNI is propagated to the bow shock / near-Earth context; it is not a raw Wind or
  ACE time series. Source-specific comparisons need timing and quality handling.
- Automatic shock/sheath/cloud boundary finding is not implied by an overview plot.
- STEREO event reproductions need spacecraft-specific coordinates, radial
  separation context, and PLASTIC/MAG quality flags before paper-quality claims.
- Variable names differ across archives; alias normalization should be explicit in
  provenance.

## Minimal provenance additions

```json
{
  "solar_wind_event": {
    "event_name": "Halloween 2003",
    "event_role": "near_earth_storm | heliospheric_icme | source_spacecraft",
    "primary_source": "OMNI HRO 1-min | Wind | ACE | STEREO-A",
    "variables": {
      "speed": "flow_speed",
      "bz": "BZ_GSM",
      "density": "proton_density",
      "dynamic_pressure": "Pressure",
      "geomagnetic_index": "SYM_H / AE_INDEX"
    },
    "boundary_status": "not_identified | paper_boundaries | event_list_boundaries",
    "quality": "paper_quality | proxy | candidate_interval"
  }
}
```

## Agent Kit feedback pattern

> Agent Kit feedback: solar-wind storm/ICME reproductions need named event presets
> plus alias-normalized overview recipes. Evidence: reproducing Skoug 2004 and
> Liu 2014 required manual OMNI `AE_INDEX` handling, STEREO MAG/PLASTIC variable
> normalization, and hand-built overview panels. Desired behavior: Agent Kit
> should produce a standard artifact bundle with source/provenance caveats and
> leave boundary finding as an explicit follow-up unless supplied by the user.
