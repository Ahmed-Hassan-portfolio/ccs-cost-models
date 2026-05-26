# Data Sources and Redistribution

Every dataset in `data/` is summarised here with its upstream source,
license, citation, and what the engine uses it for. Where redistribution
permission is uncertain, the entry is flagged.

## Top-level summary

| Path | Upstream source | License / terms | Redistributed here? |
|---|---|---|---|
| `data/netl-extracted/` | NETL `CO2_S_COM_Offshore v1.1` | BSD-3-Clause | Derived JSON/CSV only — upstream `.xlsm` NOT bundled |
| `data/regions/us-goa/formations.json` | NETL `CO2_S_COM_Offshore v1.1` Geol DB Sal sheet | BSD-3-Clause | Yes, as a derived JSON |
| `data/regions/norway-ncs/formations.json` | Sodir CO2 Storage Atlas (CCS Atlas) | NLOD 2.0 (Norwegian Licence for Open Government Data) | Yes — NLOD 2.0 allows redistribution with attribution |
| `data/regions/norway-ncs/costs.yaml` | Northern Lights public contracts (Meld. St. 33 2019-2020), SSB indices, IEAGHG 2005/2 | Public-domain Norwegian government documents and IEAGHG public report | Yes |
| `data/reference/` (mixed) | Mix of NETL, IEAGHG, SBBU NTNU report, Sodir factpages, published peer-reviewed papers | See per-file notes below | Yes — see flags |

## NETL CO2_S_COM_Offshore v1.1

- **Upstream URL.** NETL publishes the model at
  `https://netl.doe.gov/projects/files/CO2_S_COM_Offshore.zip` (US DOE,
  National Energy Technology Laboratory). The `.xlsm` workbook and its
  VBA are licensed BSD-3-Clause; this repository's `LICENSE` matches.
- **What is included here.** Derived JSON / CSV files extracted from the
  workbook by an in-house ETL pipeline (not redistributed):
  - `data/netl-extracted/formations.json` — 117 US Gulf of America saline
    formations with depth, thickness, porosity, permeability, salinity,
    structure type, area, water depth, and distance from shore.
  - `data/netl-extracted/cost_items.csv` — flattened cost catalog from the
    Cost Breakdown 1 sheet.
  - `data/netl-extracted/cost_reference_detailed.json` — totals per cost
    category for the Formation 1 default case (used by `tests/`).
  - `data/netl-extracted/storage_coefficients.json` — IEAGHG 2009/12
    storage-efficiency lookups (lithology × depositional environment ×
    structure type, with P10/P50/P90).
  - `data/netl-extracted/area_and_corrective_data.json` — per-formation
    plume area, pressure-front area, corrective-action well counts.
  - `data/netl-extracted/escalation_indices.json` — CEPCI-based annual
    factors used by the cashflow builder.
  - `data/netl-extracted/pipeline_reference.json` and
    `reference_values.json` — per-diameter pipeline cost regressions and
    intermediate validation values.
- **What is not included here.** The upstream `.xlsm` workbook, the VBA
  source, and any per-formation QUE$TOR-regression outputs (the missing
  `netl_formation_results.json` file). See LIMITATIONS.md for the
  consequence on per-formation drilling differentiation.
- **Citation.** US Department of Energy, National Energy Technology
  Laboratory, *FECM/NETL CO2 Saline Storage Cost Model — Offshore v1.1*
  (BSD-3-Clause).

## Sodir CO2 Storage Atlas (Norwegian Continental Shelf)

- **Upstream URL.** Norwegian Offshore Directorate (Sodir, ex-NPD)
  publishes the CO2 Storage Atlas at `https://www.sodir.no/en/co2-atlas/`.
- **License.** NLOD 2.0 (Norwegian Licence for Open Government Data).
  Allows redistribution and derivative works with attribution.
- **Used in.** `data/regions/norway-ncs/formations.json` (14 NCS saline
  aquifer prospects with depth, area, capacity, structural setting). The
  derived values here are formatted to match the engine's
  `FormationProperties` schema; original Atlas PDFs are not bundled.

## IEAGHG public reports

- **IEAGHG 2005/2** — *Building the Cost Curves for CO2 Storage:* used
  as the depth-based European drilling cost regression baseline for the
  NCS branch (`src/ccs_costs/costs/drilling.py:IEAGHGDrillingRegression`).
  Report is publicly available; only the quadratic depth coefficients are
  re-implemented here.
- **IEAGHG 2009/12** — *CO2 Storage in Depleted Oilfields:* source of the
  storage-efficiency P10/P50/P90 lookups in
  `data/netl-extracted/storage_coefficients.json` and
  `data/reference/storage_coefficients.json`. Public IEAGHG report.

## Northern Lights and Norwegian-government public documents

- **Meld. St. 33 (2019-2020)** — Norwegian government white paper on
  Langskip / Northern Lights, including the publicly-disclosed 33.6 % of
  Aker Solutions / Aibel contract values. These are reproduced in
  `data/regions/norway-ncs/costs.yaml` (`subsea_injection_per_well_nok`,
  `platform_control_nok`, etc.) and `data/reference/well_cost_reference.yaml`.
  All values are public-domain numbers cited verbatim from the white paper.
- **Sodir FactPages 2025** — well duration percentile bands for NCS
  injection wells (used as calibration anchors in
  `data/reference/ncs_drilling_model.yaml`). Public-domain.

## Drilling time / cost calibration anchors (NCS)

The activity-based drilling model in
`data/reference/ncs_drilling_model.yaml` cites multiple calibration data
points:

- **SBBU Standard Conventional (Sangesland et al., NTNU-IPT 2013/01)** —
  per-section activity times, two-point fit. Public NTNU report.
- **Khosravanian and Aadnoy 2021** — WBS structure, PERT distributions.
  Peer-reviewed paper.
- **Sodir FactPages 2025** — 920 NCS injection wells, percentile bands.
  Public-domain factpages.
- **Hassan, Schei, Stanko & Sangesland (2024)**,
  *Revolutionizing CCS Wells: Economically Feasible Design Innovations*,
  EAGE Earthdoc, [doi:10.3997/2214-4609.202421179](https://doi.org/10.3997/2214-4609.202421179)
  — 79 h completion time at 1000 m TVD. Used as the single calibration
  anchor for the completion-time fit; depth scaling derives from the
  physics tubing-running rate (~50 m/hr) rather than a second operator
  data point. Ahmed Hassan (this repository's author) is first author
  of the paper.

## CEPCI

`data/reference/cepci_annual.csv` lists annual Chemical Engineering Plant
Cost Index values used for cost escalation. CEPCI is a published index
(*Chemical Engineering* magazine, accessed via secondary citations); the
annual values themselves are widely reproduced in academic literature and
are reproduced here for reproducibility of the cashflow build.

## Peer-reviewed correlations

`src/ccs_costs/thermo/` and `src/ccs_costs/geo/` implement equations from
peer-reviewed publications. The coefficients are reproduced from the
published papers:

- **Duan et al. 1992** — CO2 EOS (used in `thermo/co2.py`).
- **Fenghour et al. 1998** — CO2 viscosity correlation.
- **Knoope et al. 2014** — onshore pipeline CAPEX power-law (used in
  `costs/pipeline.py` for NCS).
- **Valluri et al. 2021** — radial Darcy injectivity model.
- **Zhou et al. 2008** — simplified injectivity alternative.
- **Goodman et al. 2011** — saline aquifer storage-efficiency framework.

These coefficients are *facts* from the published record and are not
restricted; each function header in the source cites the paper.

## Reproducibility note

All extracted data files in `data/netl-extracted/` are produced by an
ETL pipeline that is **not bundled** in this portfolio mirror (it lives
in the internal research repo). Anyone with the upstream NETL `.xlsm`
files can reproduce the extracted JSON / CSV files; the engine itself
runs purely against the included data.
