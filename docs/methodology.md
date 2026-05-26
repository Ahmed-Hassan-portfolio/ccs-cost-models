# Methodology Document

Technical documentation of all equations, data sources, assumptions, and limitations in the CCS Cost Estimation Engine.

---

## 1. Overview

### System Architecture

```
                        +-----------------+
                        |   MCP Server    |
                        |  (FastMCP)      |
                        +--------+--------+
                                 |
                        +--------v--------+
                        |    Scenario      |
                        |  Orchestrator    |
                        |  (evaluate_      |
                        |   scenario)      |
                        +--------+--------+
                                 |
         +----------+----------+---------+---------+
         |          |          |         |         |
    +----v---+ +----v---+ +---v----+ +--v-----+ +-v-------+
    | Thermo | |  Geo   | | Costs  | |Finance | |Analysis |
    | co2.py | |storage | |pipeline| |cashflow| |sensitiv.|
    | brine  | |plume   | |drilling| |solver  | |monte    |
    |        | |inject  | |platform| |tax     | |supply   |
    +--------+ +--------+ +--------+ +--------+ +---------+
```

### Calculation Chain

The engine follows a strict dependency chain, matching the NETL VBA `Eval_Form` macro:

1. **Thermodynamics** -- CO2 and brine properties at reservoir and pipeline conditions
2. **Geological engine** -- Storage coefficient, plume area, injectivity, well count, schedule
3. **Cost modules** -- Pipeline, drilling, platform, monitoring, regulatory, decommissioning
4. **Financial model** -- 85-year cashflow, escalation, depreciation, tax, FYBE solver
5. **FYBE output** -- First-Year Break-Even CO2 storage price

Each stage depends on the outputs of the previous stage. The entire chain executes in a single `evaluate_scenario()` call.

---

## 2. Thermodynamics

### CO2 Density

**Duan EOS** (default method)

The primary equation of state is from Duan, Moller, and Weare (1992). This is a 15-parameter virial-type EOS for pure CO2:

```
P = RT/V + (B + C/V + D/V^4 + E/V^2) * (F + G/V^2) * exp(-G/V^2) / (V * T^3)
```

where V is molar volume, T is temperature (K), P is pressure (bar), and B through G are polynomial functions of temperature with fitted coefficients from Duan et al.

The EOS is solved for molar volume V at given (P, T) using `scipy.optimize.brentq` root-finding (replacing the VBA Newton-Raphson). Density is then:

```
rho_CO2 = MW_CO2 / V
```

where MW_CO2 = 44.0095 g/mol.

**Accuracy envelope:**
- Valid range: 0-1000 C, 0-8000 bar
- Accuracy vs. NIST Span-Wagner (1996): within 0.5% for most CCS-relevant conditions (5-40 MPa, 30-150 C)
- Inherent deviation: 1-15% in some regions (not a code bug -- fundamental EOS limitation)
- At NCS cold conditions (4 C, high pressure): produces valid results without numerical failure

**Peng-Robinson EOS** (alternative method)

Standard cubic EOS with CO2 critical properties:
- Tc = 304.1282 K, Pc = 7.3773 MPa
- Acentric factor omega = 0.225

Less accurate than Duan for CO2 at CCS conditions but provided as a cross-check.

**References:**
- Duan, Z., N. Moller, and J.H. Weare (1992). "An Equation of State for the CH4-CO2-H2O System: I. Pure Systems from 0 to 1000 C and 0 to 8000 bar." *Geochimica et Cosmochimica Acta*, 56, 2605-2617.
- Span, R. and W. Wagner (1996). "A New Equation of State for Carbon Dioxide." *J. Phys. Chem. Ref. Data*, 25(6), 1509-1596.

### CO2 Viscosity

Fenghour, Wakeham, and Vesovic (1998) correlation. The viscosity model combines a zero-density contribution, an excess contribution (function of density), and a critical enhancement term:

```
mu = mu_0(T) + mu_excess(rho) + mu_critical(T, rho)
```

where mu_0 is the dilute-gas viscosity (kinetic theory), mu_excess is from empirical density-dependent terms fitted to experimental data, and the critical enhancement is typically negligible away from the critical point.

The correlation takes density as input (from the Duan or PR EOS), not pressure directly.

**Reference:**
- Fenghour, A., W.A. Wakeham, and V. Vesovic (1998). "The Viscosity of Carbon Dioxide." *J. Phys. Chem. Ref. Data*, 27(1), 31-44.

### Brine Properties

**Brine Density:** Bandilla/Princeton correlation translating the NETL VBA `BrineDen()` function. Takes pressure (Pa), temperature (C), and salinity (mass fraction). Accounts for dissolved salt compressibility effects.

**Brine Viscosity:** Princeton correlation translating the NETL VBA `BrineVisc()` function. Same input variables as brine density.

VBA originals operate in Pa for pressure and mass fraction for salinity; the Python API converts at the boundary (MPa and ppm inputs).

---

## 3. Geological Engine

### Storage Coefficients

Storage efficiency coefficients from IEA GHG 2009/12, "Development of Storage Coefficients for CO2 Storage in Deep Saline Formations." The coefficient E represents the fraction of pore volume that will be occupied by CO2:

```
E = f(lithology, depositional_environment, structure_type, probability)
```

The lookup table contains 129 entries across:
- **Lithology:** clastic (sandstone), carbonate (limestone, dolomite)
- **Depositional environment:** shelf, slope basin, deltaic, reef, strandplain, fluvial deltaic
- **Structure type:** open (regional dip), structural closure, stratigraphic
- **Probability:** P10 (low estimate), P50 (best estimate), P90 (high estimate)

Typical values range from 0.005 (P10, tight carbonates) to 0.25 (P90, high-quality clastics).

Aliases map Norwegian/European geological terms to NETL lookup keys (e.g., sandstone -> clastic, deep_shelf -> shelf, open -> reg_dip).

**Reference:**
- IEA GHG (2009). "Development of Storage Coefficients for CO2 Storage in Deep Saline Formations." Report 2009/12.

### Plume Area

Volumetric displacement model:

```
A_plume = m_CO2 / (E * h * phi * rho_CO2)
```

where:
- m_CO2 = total CO2 mass injected (kg) = injection_rate * operations_years * 1000
- E = storage coefficient (dimensionless)
- h = formation thickness (m) -- gross thickness, since E already incorporates net-to-gross
- phi = porosity (fraction)
- rho_CO2 = CO2 density at reservoir (P, T) in kg/m3

Result in m2, converted to km2. The plume area drives monitoring well placement and Area of Review calculations.

**Uncertainty and pressure front multipliers:**
- Uncertainty area = plume_area * 1.25 (default)
- Pressure front (AoR) = uncertainty_area * 5.0 (default)

### Injectivity

**Valluri Method** (default, Method 7 in NETL)

Steady-state radial Darcy flow for CO2 injection into a brine-saturated formation:

```
Q = (2 * pi * k * h * delta_P) / (mu_CO2 * ln(r_e / r_w))
```

where:
- k = permeability (m2; converted from mD by multiplying by 9.869e-16)
- h = formation thickness (m)
- delta_P = P_fracture - P_reservoir (Pa)
- mu_CO2 = CO2 viscosity at reservoir conditions (Pa-s)
- r_e = drainage radius (default 10,000 m)
- r_w = wellbore radius (default 0.1 m)

NETL uses CO2 viscosity in the Darcy denominator (single-phase approximation; far-field brine displacement is not rate-limiting at formation scale). The volumetric rate (m3/s) is converted to mass rate (tonnes/day) using CO2 density, then capped at 3,660 t/day per well.

**Zhou Simplified Method** (alternative, Method 1)

Uses the same Darcy equation but with CO2 viscosity as the effective viscosity (single-phase upper bound). Provided as a conservative alternative.

**Fracture Pressure Estimation:**

When formation-specific fracture pressure data is not available:

```
P_fracture = gradient * depth_m
```

where gradient = 0.01638 MPa/m (~0.72 psi/ft), calibrated to the NETL "min calculated frac pressure" approach.

For US-GOA formations, extracted NETL fracture pressures from the Res_Bas1 worksheet (column 53) are used directly.

**References:**
- Valluri, M.K., S. Mukherjee, R. Mishra, and A. Gilmore (2021). "An improved understanding of CO2 injectivity." *Int. J. Greenhouse Gas Control*, 112.
- Zhou, Q., J.T. Birkholzer, C.F. Tsang, and J. Rutqvist (2008). "A method for quick assessment of CO2 storage capacity in closed and semi-closed saline formations." *Int. J. Greenhouse Gas Control*, 2(4), 626-639.

### Well Count

**Injection wells:**

```
n_active = ceil(injection_rate_tpa / (max_rate_per_well * capacity_factor * 365.25))
n_injection = n_active + 1  (NETL convention: +1 spare well)
```

**Monitoring wells:** Satellite pattern based on injection well count:

```
n_monitoring = (n_injection + 1) * (n_reservoir + n_above_seal)
```

where n_reservoir and n_above_seal are monitoring well layers (NETL default: 12 per injection well for O&M satellite pattern). Note: only 2 physical in-reservoir monitoring wells are drilled for cost purposes.

### Project Schedule

85-year total project timeline with 6 stages:

| Stage | Duration | Description |
|-------|----------|-------------|
| Screening | 1 year | Site identification |
| Characterization | 2 years | Geological characterization |
| Permitting | 2 years | Regulatory permitting (combined with construction in NETL) |
| Construction | 0-3 years | Facility construction (0 for NETL, 3 for Norway) |
| Operations | 30 years | CO2 injection period (configurable) |
| PISC | 50 or 20 years | Post-Injection Site Care (50 US, 20 EU) |

Year-by-year plume tracking follows NETL `Plume&Well Schedule` with CO2 volume, density, and plume radius computed at each time step.

---

## 4. Cost Modules

### Pipeline

**Hydraulic Sizing:**

Darcy-Weisbach equation with Colebrook-White friction factor for incompressible liquid CO2:

```
D_min = (32 * f_F * qm^2 * L / (pi^2 * rho * delta_P))^0.2
```

where:
- f_F = Fanning friction factor from Colebrook-White (iterative)
- qm = mass flow rate (kg/s)
- L = pipeline length (m)
- rho = CO2 density at pipeline conditions (kg/m3)
- delta_P = inlet pressure - outlet pressure (Pa)

The iterative algorithm: (1) guess D = 0.5 m, (2) compute Reynolds number Re = 4*qm/(pi*mu*D), (3) compute Fanning friction via Colebrook-White, (4) compute new D, (5) repeat until convergence. The minimum diameter is rounded up to the next standard pipe size (4", 6", 8", 10", 12", 16", 20", 24", 30", 36", 42", 48").

Pipeline conditions use mudline temperature (12.78 C / 55 F for GOA, 4 C for NCS) and average pipeline pressure (~11.72 MPa).

**Cost Models:**

*NETL/QUE$TOR piecewise-linear* (US-GOA):
```
CAPEX = slope * L_miles + intercept   (2022$, by diameter bin)
```

Five diameter bins (6", 8", 12", 16", 20") with different slopes and intercepts extracted from NETL VBA. Pipeline O&M is annual by diameter with a PISC reduction factor of 0.778.

*Knoope 2014 power-law* (European):
```
CAPEX = a * D^b * L   (EUR, 2013$)
```

where a = 3,230,000, b = 1.77, D is outer diameter (m), L is length (km). Fitted to 14+ European CO2 pipeline cost datasets.

**References:**
- Knoope, M.M.J., A. Ramirez, and A.P.C. Faaij (2013/2014). "A state-of-the-art review of techno-economic models predicting the costs of CO2 pipeline transport." *Int. J. Greenhouse Gas Control*, 16, 241-270; 22, 25-46.
- McCoy, S.T. and E.S. Rubin (2008). "An engineering-economic model of pipeline transport of CO2." *Int. J. Greenhouse Gas Control*, 2, 219-229.

### Drilling

**NETL Lookup** (US-GOA):

Per-well drilling costs extracted from NETL VBA as lookup tables indexed by formation depth. Separate costs for:
- Injection wells (vary by depth and water depth)
- Monitoring wells (in-reservoir, 2 drilled)
- Stratigraphic test wells (1 per project)

Costs in 2022$ base year, part of the extracted NETL reference data.

**IEAGHG 2005/2 Quadratic Regression** (European):

```
Cost = a + b * depth + c * depth^2   (EUR, year-2000 base)
```

TNO-derived regression for European well costs. Applied with a 2.3x escalation factor (2000 -> 2024 indicative, based on SSB PPI Oil & Gas). The `DrillingRegression` Protocol enables pluggable regressions -- NETL, IEAGHG, and future Oliasoft are all interchangeable.

**Reference:**
- IEAGHG (2005). "Building the Cost Curves for CO2 Storage: European Sector." Report 2005/2.

### Infrastructure

**Platform Jacket** (US-GOA):

NETL reference costs extracted from the VBA model. Primary and satellite platforms with costs dependent on water depth and well count. Includes platform O&M during operations and PISC.

**Subsea Tieback** (Norway-NCS):

Based on Northern Lights Phase 1 contracts (2020 awards, 33.6% disclosed):
- Subsea injection system: NOK 250M per well (Aker Solutions)
- Platform control system: NOK 140M one-time (Aibel)
- Manifold: NOK 80M per template unit
- Umbilical: NOK 5M per km
- Annual O&M: 3% of CAPEX

Tagged **Confidence C** -- limited evidence, Northern Lights anchored only.

### Monitoring

Monitoring costs are reverse-engineered from NETL lifetime totals decomposed into per-unit/per-year rates. Technologies include:

| Technology | Stage | Cost Structure |
|------------|-------|----------------|
| Subsea monitoring | Char + Ops + PISC | Baseline capital + annual campaigns |
| 3-D seismic | Ops + PISC | Per-event, every 5 years |
| 2-D seismic | PISC only | Per-event |
| Microseismic | Ops + PISC | Equipment capital + annual |
| Well integrity | Ops | Per well per year |
| Well O&M (injection) | Ops | Per well per year |
| Well O&M (in-reservoir) | Ops + PISC | Per well per year |
| Gravity survey | Char | One-time capital |

Norwegian costs are scaled from US costs by vessel rate ratios (5-10x) and weather downtime (20% NCS vs 7% GOA). Costs are stored in region-specific `monitoring.yaml` files.

### Regulatory

**US (EPA/BOEM):**
- Pore space fees: $30M one-time
- Emergency & Remedial Response (ERR): $90M
- Stewardship fees: $8.4M annual during PISC
- EPA injection permit: annual fee
- Subpart RR reporting: annual

**Norway/EU (CCS Directive):**
- CO2 storage permit application: NOK 25M
- PDO preparation: NOK 50M
- EIA: NOK 15M
- EU MRV reporting: NOK 1M/yr
- No pore space fees (production license model)
- No stewardship fees
- No ERR fees

### Decommissioning

Well plugging and abandonment costs during the PISC phase, scaled by well count. Pipeline decommissioning is handled within the pipeline cost module (not double-counted).

---

## 5. Financial Model

### Cashflow Model

85-year cashflow model matching the NETL `FinMod_Main` worksheet structure. For each project year:

```
Net Cashflow = Revenue - OPEX - CAPEX - Tax - Interest
```

where:
- **Revenue** = CO2 price (FYBE) * annual CO2 injected * escalation factor
- **OPEX** = sum of all expense-classified cost items for that year, escalated
- **CAPEX** = sum of all capital-classified cost items for that year, escalated
- **Tax** = (Revenue - OPEX - Depreciation - Interest) * tax_rate (if positive)
- **Interest** = outstanding_debt * cost_of_debt

NETL convention: year 1 is undiscounted (discount factor = 1.0).

### Escalation

**Two-stage escalation:**

1. **Pre-project** (base year -> project start): applied via `base_to_start_factor`
   - US-GOA: Handy-Whitman factor 2.849x (2008 -> 2024, from NETL VBA)
   - Norway: 1.0x (costs already in 2024 NOK)

2. **During project** (annual compounding from project start):
   - US-GOA: uses NETL pre-computed annual factors
   - Norway: 2% annual (aligned with SSB construction cost index)

```
escalated_cost = base_cost * base_to_start_factor * (1 + during_rate)^(year - start_year)
```

### Depreciation

Four methods available, selected per cost category in region `finance.yaml`:

| Method | Code | Description |
|--------|------|-------------|
| Straight Line | `SL` | Equal annual deductions over recovery period |
| 150% Declining Balance | `DB150` | 1.5x straight-line rate, switching to SL |
| 200% Declining Balance | `DB200` | 2x straight-line rate, switching to SL |
| Norwegian Linear | `NO_LIN` | Equal annual deductions, 6-year period (offshore) |

MACRS tables (US) are stored as hardcoded tuples extracted from VBA -- not computed from first principles.

### Tax Regimes

**US (25.74% effective rate):**
- Federal corporate rate applied after MACRS depreciation deductions
- Interest expense is tax-deductible
- Loss carryforward available

**Norway (22% corporate rate):**
- Norwegian corporate tax only -- CCS is explicitly excluded from the 56% petroleum special tax
- Norwegian linear 6-year depreciation for all offshore assets
- Interest deductible
- Loss carryforward

### Revenue Streams (Norwegian)

Norwegian scenarios include two additional revenue streams that reduce the effective break-even price:

**EU ETS Credits:** ~EUR 70/t (2024), escalating at 2%/year. Applied to each tonne of CO2 stored during operations.

**Norwegian CO2 Tax:** ~EUR 70/t (converted from NOK 790/t at indicative rates). Applied per tonne of CO2 stored.

Revenue streams make it possible for FYBE to be negative -- meaning the project is profitable even without charging a storage fee, because the ETS + CO2 tax revenues exceed total costs.

### FYBE Solver

The First Year Break-Even (FYBE) solver finds the CO2 storage price that makes NPV = 0:

```
NPV(FYBE) = sum over t=1..85 of (net_cashflow_t / (1 + r_equity)^t) = 0
```

Implementation uses `scipy.optimize.brentq` root-finding with:
- Default bracket: [0, 500] $/t
- Auto-expansion to negative prices for Norwegian scenarios
- Tolerance: 0.0001 $/t
- Discount rate: cost of equity (10.8% US, 8% Norway), not WACC

The solver replaces the Excel GoalSeek binary search in the NETL model with guaranteed convergence.

### Financial Metrics

| Metric | Formula | Notes |
|--------|---------|-------|
| NPV | Discounted sum of net cashflows at cost of equity | ~$0 at FYBE by definition |
| IRR | Rate where NPV = 0 | Solved via brentq, bracket [-0.5, 10.0] |
| LCOE | Total cost (real) / total CO2 stored | Approximate levelized cost |

---

## 6. Analysis Subsystem

The analysis module provides four tools for exploring parameter sensitivity, uncertainty quantification, and formation ranking. All analysis functions call `evaluate_scenario()` internally, running the full calculation chain for each sample or parameter step.

### One-Way Sensitivity Analysis

**Function:** `run_one_way_sensitivity(formation_id, region, parameter, min_value, max_value, steps=7)`

Sweeps a single parameter across its range in N evenly-spaced steps (default 7). At each step, the parameter value is applied as a `formation_override` or `economic_override` on the base scenario, and a full `evaluate_scenario()` call produces the FYBE at that parameter value.

- Returns a list of `{param_value, fybe}` pairs tracing the FYBE-vs-parameter curve
- Failed evaluations return `fybe: None` with an error message -- they do not abort the sweep
- Useful for identifying nonlinear cost responses (e.g., permeability thresholds where additional wells are needed)

### Tornado Analysis

**Function:** `run_tornado_sensitivity(formation_id, region, parameter_ranges, steps=7)`

Runs one-way sensitivity for each parameter in a dictionary of `{param_name: [min_value, max_value]}`. For each parameter, computes the FYBE swing:

```
swing = max(FYBE across steps) - min(FYBE across steps)
```

Parameters are sorted by swing in descending order (largest cost impact first). Returns for each parameter:
- `fybe_at_low`: FYBE when parameter is at its minimum
- `fybe_base`: FYBE at the formation's default value
- `fybe_at_high`: FYBE when parameter is at its maximum
- `swing`: total FYBE range

This ranking identifies which geological or economic uncertainties matter most for a given formation.

### Supply Curve

**Function:** `run_supply_curve(region, injection_rate_mtpa)`

Evaluates all formations in a region at the specified injection rate and sorts successful formations by FYBE in ascending order (cheapest storage first). This produces a merit-order ranking for regional storage capacity planning.

- Failed formations are appended at the end with `fybe: null` and an error description -- nothing is silently dropped
- Each entry includes well count, CAPEX, OPEX, and storage capacity for context
- The cumulative capacity vs. FYBE curve shows how much storage is available at each price point

### Monte Carlo Simulation

**Function:** `run_monte_carlo(formation_id, region, n_samples=1000, uncertainty_config=None, seed=42)`

Samples parameter distributions from `data/regions/{region}/uncertainty.yaml` and runs `evaluate_scenario()` for each sample to produce a probabilistic FYBE distribution.

**Distribution types supported:** triangular, uniform, normal, lognormal.

**Parameter application:** Each parameter can be `relative` (multiplied by the formation's base value) or `absolute` (used directly). Relative parameters allow the same uncertainty specification across formations with different base values.

**Parallelization:** Uses `ProcessPoolExecutor` with 8 workers to bypass the GIL for CPU-bound cashflow calculations. A sequential fallback activates if the process pool spawn fails (Windows safety net).

**Output statistics:** P10, P50 (median), P90, mean, standard deviation, min, max from the FYBE distribution, plus counts of successful and failed samples.

**Default configuration:** 1000 samples with `seed=42` for reproducibility. Performance: approximately 52 seconds for 1000 samples (target: <120 seconds).

**Default US-GOA uncertainty specifications:**

| Parameter | Distribution | Type | Range |
|-----------|-------------|------|-------|
| porosity | triangular | relative | 0.8x - 1.0x - 1.2x |
| permeability_md | triangular | relative | 0.5x - 1.0x - 2.0x |
| thickness_m | triangular | relative | 0.8x - 1.0x - 1.2x |
| depth_m | triangular | relative | 0.9x - 1.0x - 1.1x |
| net_to_gross | triangular | relative | 0.8x - 1.0x - 1.2x |
| injection_rate_mtpa | uniform | relative | 0.8x - 1.2x |

Note: Porosity and depth do not affect FYBE in the NETL model because NETL uses fixed per-well drilling lookup costs (not depth-dependent) and porosity only affects plume tracking (not cost calculations). Permeability and injection rate are the primary cost drivers through their effect on well count.

---

## 7. Assumptions and Limitations

### Key Assumptions

1. **Saline aquifer only** -- no depleted oil/gas fields, no EOR
2. **Vertical wells** -- no directional or horizontal wells modeled
3. **Volumetric approach** -- plume area from simple displacement, no numerical simulation
4. **Steady-state injectivity** -- no transient effects, no pressure buildup modeling
5. **Single-phase Darcy** -- CO2 viscosity used in Darcy law (far-field brine not rate-limiting)
6. **Offshore only** -- onshore configurations not supported in v1.0
7. **Single formation per scenario** -- no multi-zone injection
8. **Constant injection rate** -- no ramp-up or decline curves

### Known Limitations

| Component | Limitation | Confidence | Mitigation |
|-----------|------------|------------|------------|
| Subsea tieback costs | Northern Lights anchored only (33.6% disclosed) | C | Use sensitivity analysis on infrastructure costs |
| No ship transport | Pipeline-only transport; ship/barge not modeled | -- | Out of scope for v1.0 |
| No depleted fields | Only saline aquifer storage coefficients | -- | IEA GHG coefficients are aquifer-specific |
| Pipeline: no terrain | Flat seabed assumed; no terrain routing | B | Routing factor (1.1x default) partially compensates |
| IEAGHG drilling | Year-2000 base costs with indicative 2.3x escalation | C | Use Oliasoft or operator data when available |
| Duan EOS | 1-15% deviation from Span-Wagner in some P-T regions | B | Acceptable for cost estimation; optional Multiflash MCP for Span-Wagner |
| Norwegian revenue streams | ETS price and CO2 tax assumed constant or simply escalating | B | Monte Carlo with ETS price distribution |
| Formation data quality | Some NCS formations have estimated (not measured) properties | B-C | Monte Carlo addresses parameter uncertainty |

### Accuracy Envelopes by Module

| Module | Cross-verification | Tolerance | Notes |
|--------|-------------------|-----------|-------|
| Thermodynamics | NIST Span-Wagner | 0.5% most conditions | Duan EOS inherent limitation |
| Geological engine | NETL 117 formations | Well count exact for 110/117 | 7 storage-cap formations excluded (different well-count method) |
| Pipeline sizing | NETL default | Exact (12") | Hydraulic sizing matches VBA |
| Cost catalog | NETL totals | < 1% | CAPEX $521M vs NETL $518M, OPEX $1,214M vs $1,207M |
| FYBE (calibration formation) | NETL Formation 1241_1 | $0.42/t | Engine $25.76 vs NETL $25.34 (1.7% deviation) |
| FYBE (other GOA formations) | NETL 117 formations | Unverified in this mirror | Per-formation QUE$TOR-regression file not bundled; all formations fall back to Formation 1 drilling costs (see LIMITATIONS.md) |
| NCS formations | Northern Lights | Confidence C | IEAGHG 2005 regression, 40-70% lower than NL actual costs |

In this portfolio mirror the engine uses fixed per-well drilling lookup costs (the Formation 1 NETL row80/86/95 totals divided by their well counts) for every formation. The depth-dependent QUE$TOR polynomial that drives per-formation differentiation in the NETL Excel model lives in the optional `netl_formation_results.json` file, which is not bundled — see LIMITATIONS.md. The calibration formation (1241_1) is the only formation where the engine's drilling costs and NETL's drilling costs are constructed from the same inputs, so it is the only formation with a well-defined FYBE comparison. For NCS formations, the IEAGHG 2005/2 drilling regression produces costs 40-70% below Northern Lights actual contract values, reflecting the year-2000 European cost base before North Sea cost escalation. Use Oliasoft or operator-specific data for production-grade NCS estimates.

---

## 8. Data Sources

| Source | Data Type | Provenance | License | Used In |
|--------|-----------|------------|---------|---------|
| NETL CO2_S_COM v4 | VBA code, 117 formations, cost lookup tables | US DOE National Energy Technology Laboratory | BSD-3 | All US-GOA calculations |
| NETL Offshore v1.1 | Offshore-specific VBA, platform costs | US DOE NETL | BSD-3 | Pipeline, platform, monitoring |
| IEA GHG 2009/12 | Storage coefficients (129 entries) | IEA Greenhouse Gas R&D Programme | Public report | Storage efficiency |
| Duan et al. (1992) | CO2 EOS coefficients | Published paper | Academic | CO2 density |
| Fenghour et al. (1998) | CO2 viscosity correlation | Published paper | Academic | CO2 viscosity |
| Knoope et al. (2014) | Pipeline cost power-law | Published paper | Academic | European pipeline CAPEX |
| Valluri et al. (2021) | Injectivity method | Published paper | Academic | Injection rate |
| Zhou et al. (2008) | Simplified injectivity | Published paper | Academic | Alternative injection rate |
| IEAGHG 2005/2 | European well cost regression | IEA GHG report | Public report | Norwegian drilling costs |
| Northern Lights | Subsea contracts (33.6% disclosed) | Meld. St. 33 (2019-2020) | Public | NCS infrastructure costs |
| Sodir CO2 Storage Atlas | 76 CO2 features, formation properties | Norwegian Offshore Directorate GDB | NLOD 2.0 | NCS formation database |
| SSB | Construction cost indices, wages | Statistics Norway | Open data | Norwegian escalation |
| Handy-Whitman | Cost escalation factors (2.849x) | Pre-computed from NETL VBA | NETL embedded | US escalation 2008-2024 |
