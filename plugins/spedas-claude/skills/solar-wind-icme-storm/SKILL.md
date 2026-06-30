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
