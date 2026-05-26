# User Guide

Practical guide for running CCS cost scenarios, adding formations, and extending the engine with new regions.

---

## 1. Quick Start

### Installation

```bash
# Clone and install in development mode
git clone <repo-url>
cd ccs-cost-models
pip install -e .
```

### Start the MCP Server

```bash
ccs-cost-server
```

The server starts a FastMCP process exposing 10 tools. Connect any MCP-compatible client (Claude Desktop, custom agent, etc.).

### First MCP Call

```json
{
  "tool": "estimate_storage_cost",
  "arguments": {
    "formation": "1241_1",
    "region": "us-goa"
  }
}
```

### First Python Call

```python
from ccs_costs.scenario import ScenarioConfig, evaluate_scenario

config = ScenarioConfig(formation_id="1241_1", region="us-goa")
result = evaluate_scenario(config)
print(f"FYBE: ${result.fybe:.2f}/t ({result.base_year}$)")
```

---

## 2. Worked Example: NETL Default Formation (US-GOA)

This example evaluates the NETL reference formation -- Formation 1241_1, Chandeleur Area Block 37, Sand 1 -- in the US Gulf of America offshore region. This formation is the cross-verification benchmark: the Python engine should reproduce the NETL Excel model results.

**Expected results:**
- FYBE (2008$): ~$25.76/t (engine output; NETL reference: $25.34/t → 1.7% deviation)
- FYBE (2024$): ~$73.41/t (engine output; NETL reference: ~$72.20/t)
- Injection wells: 5 (4 active + 1 spare)
- Pipeline diameter: 12 inches
- Infrastructure: platform jacket

### MCP Tool Call

```json
{
  "tool": "estimate_storage_cost",
  "arguments": {
    "formation": "1241_1",
    "region": "us-goa",
    "injection_rate_mtpa": 4.0
  }
}
```

**Response (abbreviated):**

```json
{
  "formation_id": "1241_1",
  "formation_name": "Chandeleur Area Block 37, Sand 1",
  "region": "us-goa",
  "fybe": 25.76,
  "fybe_current_year": 73.41,
  "n_injection_wells": 5,
  "n_monitoring_wells": 24,
  "pipeline_diameter_inches": 12,
  "pipeline_length_km": 60.8,
  "total_capex": 520663417,
  "total_opex": 1214197945,
  "total_co2_stored_mt": 120.0,
  "currency": "USD",
  "base_year": 2008
}
```

### Python API

```python
from ccs_costs.scenario import ScenarioConfig, evaluate_scenario

config = ScenarioConfig(
    formation_id="1241_1",
    region="us-goa",
    injection_rate_tpa=4_000_000,  # 4 Mt/yr (NETL default)
)

result = evaluate_scenario(config)

# Primary outputs
print(f"FYBE (2008$): ${result.fybe:.2f}/t")
print(f"FYBE (2024$): ${result.fybe_current_year:.2f}/t")

# Geological outputs
print(f"CO2 density: {result.co2_density_kgm3:.1f} kg/m3")
print(f"Storage coefficient: {result.storage_coefficient}")
print(f"Plume area: {result.plume_area_km2:.1f} km2")

# Infrastructure outputs
print(f"Injection wells: {result.n_injection_wells}")
print(f"Pipeline: {result.pipeline_diameter_inches}\" x {result.pipeline_length_km:.1f} km")

# Cost outputs
print(f"Total CAPEX: ${result.total_capex/1e6:.0f}M")
print(f"Total OPEX: ${result.total_opex/1e6:.0f}M")
print(f"Total CO2 stored: {result.total_co2_stored_mt:.1f} Mt")
```

---

## 3. Worked Example: Johansen (Norway-NCS)

This example evaluates the Johansen formation on the Norwegian Continental Shelf -- the primary target for the Northern Lights CCS project. The Norwegian region uses different financial parameters, infrastructure paradigm, and revenue streams compared to the US.

**Key differences from US-GOA:**
- Infrastructure: subsea tieback (not platform jacket)
- Tax regime: 22% Norwegian corporate tax (not 25.74% US)
- Revenue streams: EU ETS credits (~EUR 70/t) + Norwegian CO2 tax (~EUR 70/t)
- PISC period: 20 years (EU CCS Directive) vs. 50 years (US EPA)
- Drilling: IEAGHG 2005/2 regression (not NETL lookup)
- Pipeline: Knoope 2014 power-law (not NETL/QUE$TOR piecewise)
- Currency: NOK (base year 2024)

**Expected result:** FYBE approximately EUR 18/t (negative FYBE possible due to ETS + CO2 tax revenue exceeding costs).

### MCP Tool Call

```json
{
  "tool": "estimate_storage_cost",
  "arguments": {
    "formation": "ncs_johansen",
    "region": "norway-ncs",
    "injection_rate_mtpa": 3.0
  }
}
```

### Python API

```python
from ccs_costs.scenario import ScenarioConfig, evaluate_scenario

config = ScenarioConfig(
    formation_id="ncs_johansen",
    region="norway-ncs",
    injection_rate_tpa=3_000_000,  # 3 Mt/yr
)

result = evaluate_scenario(config)

print(f"FYBE: {result.fybe:.2f} {result.currency}/t ({result.base_year})")
print(f"FYBE (current): {result.fybe_current_year:.2f} {result.currency}/t")
print(f"Infrastructure: subsea tieback")
print(f"Wells: {result.n_injection_wells} injection, {result.n_monitoring_wells} monitoring")
print(f"Pipeline: {result.pipeline_diameter_inches}\" x {result.pipeline_length_km:.1f} km")
```

### Comparing Multiple Norwegian Formations

Use the supply curve tool to rank all NCS formations by cost:

```json
{
  "tool": "run_supply_curve",
  "arguments": {
    "region": "norway-ncs",
    "injection_rate_mtpa": 3.0
  }
}
```

Or in Python:

```python
from ccs_costs.analysis import run_supply_curve

sc = run_supply_curve(region="norway-ncs", injection_rate_mtpa=3.0)
for f in sc["formations"][:5]:
    if f.get("fybe") is not None:
        print(f"  {f['formation_name']}: FYBE={f['fybe']:.2f} NOK/t")
```

---

## 4. Adding a New Formation

Formations are stored in `data/regions/{region}/formations.json`. To add a new formation, append an entry to the `formations` array.

### Required Fields

| Field | Type | Units | Description |
|-------|------|-------|-------------|
| `id` | `str` | -- | Unique identifier (lowercase, underscores) |
| `name` | `str` | -- | Human-readable name |
| `depth_m` | `float` | m | Formation top depth |
| `thickness_m` | `float` | m | Gross formation thickness |
| `porosity` | `float` | fraction | Porosity (0-1) |
| `permeability_md` | `float` | mD | Permeability in millidarcies |
| `temperature_c` | `float` | C | Reservoir temperature |
| `pressure_mpa` | `float` | MPa | Reservoir pressure |
| `salinity_ppm` | `float` | ppm | Brine salinity (mg/L) |
| `water_depth_m` | `float` | m | Water depth at site |
| `distance_from_shore_km` | `float` | km | Distance from shore (pipeline length proxy) |
| `lithology` | `str` | -- | `"sandstone"`, `"limestone"`, `"dolomite"` |
| `depositional_environment` | `str` | -- | See table below |
| `structure_type` | `str` | -- | `"open"`, `"structural_closure"`, `"stratigraphic"` |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `net_to_gross` | `float` | `1.0` | Net-to-gross ratio |
| `data_quality` | `str` | `"estimated"` | `"measured"`, `"estimated"`, `"default"` |
| `fracture_pressure_mpa` | `float` | computed | Override fracture pressure |
| `area_km2` | `float` | computed | Override formation area |

### Depositional Environment Values

| Value | Alias | Description |
|-------|-------|-------------|
| `shelf` | `deep_shelf`, `marine_shelf` | Continental shelf deposits |
| `slope basin` | `turbidite`, `submarine_fan` | Slope and basin floor |
| `reef` | -- | Reef/carbonate buildup |
| `deltaic` | `fluvial_deltaic` | Delta and delta-front |
| `strandplain` | `coastal`, `barrier` | Barrier island / strandplain |

### Example Entry

```json
{
  "id": "my_new_formation",
  "name": "My New Formation",
  "depth_m": 2500,
  "thickness_m": 120,
  "net_to_gross": 0.85,
  "porosity": 0.22,
  "permeability_md": 200,
  "temperature_c": 75.0,
  "pressure_mpa": 25.0,
  "salinity_ppm": 40000,
  "water_depth_m": 150,
  "distance_from_shore_km": 80,
  "lithology": "sandstone",
  "depositional_environment": "shelf",
  "structure_type": "open",
  "data_quality": "estimated"
}
```

After adding the entry, the formation is immediately available for evaluation:

```python
result = evaluate_scenario(ScenarioConfig(
    formation_id="my_new_formation",
    region="norway-ncs",
))
```

---

## 5. Adding a New Region

Regions are self-contained directories under `data/regions/{region}/`. Each region requires 6 configuration files.

### Directory Structure

```
data/regions/{region}/
  costs.yaml         # Infrastructure model, pipeline coefficients, vessel rates, timeline
  finance.yaml       # Tax rates, capital structure, escalation, depreciation, revenue streams
  formations.json    # Formation database (at least one formation)
  monitoring.yaml    # Monitoring technologies and unit costs
  regulatory.yaml    # Regulatory fee schedule
  uncertainty.yaml   # Monte Carlo parameter distributions
```

### Step-by-Step Guide

#### 1. Create the region directory

```bash
mkdir -p data/regions/my-region
```

#### 2. Create `costs.yaml`

```yaml
# Region cost parameters
region: my-region
base_year: 2024
currency: EUR

# Infrastructure model: 'platform_jacket' or 'subsea_tieback'
infrastructure:
  model: subsea_tieback

# Drilling cost regression
drilling:
  regression: ieaghg_2005

# Vessel rates (currency/day)
vessel_rates:
  supply_vessel_day: 25000
  construction_vessel_day: 150000

# Environmental conditions
mudline_temperature_c: 4
weather_downtime_pct: 0.20

# Project timeline
timeline:
  screening_years: 1
  characterization_years: 2
  permitting_years: 2
  construction_years: 3
  operations_years: 30
  pisc_years: 20

# Pipeline cost model
pipeline:
  routing_factor: 1.1
  pisc_om_factor: 0.778
```

#### 3. Create `finance.yaml`

```yaml
# Financial parameters
tax:
  corporate_rate: 0.22
  use_petroleum_tax: false
  loss_carryforward: true

capital_structure:
  equity_fraction: 0.30
  cost_of_equity: 0.08
  cost_of_debt: 0.035

escalation:
  base_cost_year: 2024
  project_start_year: 2028
  pre_project_rate: 0.0
  during_project_rate: 0.02

depreciation_map:
  site_characterization:
    method: NO_LIN
    recovery_period: 6
  seismic:
    method: NO_LIN
    recovery_period: 6
  wells:
    method: NO_LIN
    recovery_period: 6
  plug_abandon:
    method: NO_LIN
    recovery_period: 6
  pipeline:
    method: NO_LIN
    recovery_period: 6
  platform:
    method: NO_LIN
    recovery_period: 6

# Optional: revenue streams (ETS credits, CO2 tax, subsidies)
revenue_streams:
  ets_price_eur_per_tonne: 70.0
  co2_tax_per_tonne: 0.0
  government_grant_fraction: 0.0
  ets_escalation_rate: 0.02
  co2_tax_escalation_rate: 0.0

financial_security:
  type: parent_company_guarantee
  annual_cost_fraction: 0.005
```

#### 4. Create `formations.json`

```json
{
  "_metadata": {
    "source": "Description of data source",
    "region": "my-region",
    "units": "SI (metres, Celsius, MPa, mD, mg/L, km)",
    "formation_count": 1
  },
  "formations": [
    {
      "id": "example_formation",
      "name": "Example Formation",
      "depth_m": 2000,
      "thickness_m": 100,
      "net_to_gross": 1.0,
      "porosity": 0.20,
      "permeability_md": 150,
      "temperature_c": 60.0,
      "pressure_mpa": 20.0,
      "salinity_ppm": 35000,
      "water_depth_m": 100,
      "distance_from_shore_km": 50,
      "lithology": "sandstone",
      "depositional_environment": "shelf",
      "structure_type": "open",
      "data_quality": "estimated"
    }
  ]
}
```

#### 5. Create `monitoring.yaml`

```yaml
base_year: 2024
currency: EUR

monitoring_technologies:
  subsea_monitoring:
    characterization_cost: 10000000
    construction_capital: 5000000
    annual_ops_cost: 3000000
    annual_pisc_cost: 4000000
    classification_capital: capital
    classification_ops: expense
    depreciation: site_characterization

  seismic_3d:
    frequency_years: 5
    ops_cost_per_event: 5000000
    pisc_cost_per_event: 6000000
    classification: capital
    depreciation: seismic
```

#### 6. Create `regulatory.yaml`

```yaml
base_year: 2024
currency: EUR

regulatory_items:
  - id: storage_permit
    name: "Storage permit application"
    amount: 2000000
    classification: capital
    stage: characterization
    recurrence: one-time
    depreciation: site_characterization

  - id: eia
    name: "Environmental Impact Assessment"
    amount: 1500000
    classification: capital
    stage: characterization
    recurrence: one-time
    depreciation: site_characterization
```

#### 7. Create `uncertainty.yaml`

```yaml
# Monte Carlo parameter distributions
parameters:
  permeability_md:
    distribution: triangular
    relative: true
    min: 0.5
    mode: 1.0
    max: 2.0

  porosity:
    distribution: triangular
    relative: true
    min: 0.8
    mode: 1.0
    max: 1.2
```

### Verify the Region

```python
from ccs_costs.config import load_region, list_available_regions

# Check your region appears
print(list_available_regions())

# Load and inspect
rc = load_region("my-region")
print(f"Region: {rc.name}")
print(f"Currency: {rc.currency}")
print(f"Formations: {len(rc.formations)}")

# Run a scenario
from ccs_costs.scenario import ScenarioConfig, evaluate_scenario
result = evaluate_scenario(ScenarioConfig(
    formation_id="example_formation",
    region="my-region",
))
print(f"FYBE: {result.fybe:.2f} {result.currency}/t")
```

### Reference: Existing Regions

Use `data/regions/norway-ncs/` as the primary template for European regions, or `data/regions/us-goa/` for US regions.

---

## 6. Analysis Tools

### One-Way Sensitivity

Sweep a single parameter to see its effect on FYBE:

```python
from ccs_costs.analysis import run_one_way_sensitivity

results = run_one_way_sensitivity(
    formation_id="ncs_johansen",
    region="norway-ncs",
    parameter="permeability_md",
    min_value=50,
    max_value=500,
    steps=7,
)

for r in results:
    fybe = r['fybe']
    if fybe is not None:
        print(f"  k={r['param_value']:.0f} md -> FYBE={fybe:.2f}")
```

### Tornado Analysis

Rank parameters by FYBE impact:

```python
from ccs_costs.analysis import run_tornado_sensitivity

tornado = run_tornado_sensitivity(
    formation_id="ncs_johansen",
    region="norway-ncs",
    parameter_ranges={
        "permeability_md": [50, 500],
        "thickness_m": [50, 300],
        "depth_m": [2000, 3500],
    },
    steps=3,
)

for entry in tornado:
    print(f"  {entry['parameter']}: swing={entry['swing']:.2f}, "
          f"low={entry['fybe_at_low']:.2f}, high={entry['fybe_at_high']:.2f}")
```

### Monte Carlo Simulation

Probabilistic FYBE with parameter distributions:

```python
from ccs_costs.analysis import run_monte_carlo

mc = run_monte_carlo(
    formation_id="ncs_johansen",
    region="norway-ncs",
    n_samples=1000,
    seed=42,
)

print(f"P10: {mc['p10']:.2f}")
print(f"P50: {mc['p50']:.2f} (median)")
print(f"P90: {mc['p90']:.2f}")
print(f"Mean: {mc['mean']:.2f}")
print(f"Success rate: {mc['n_success']}/{mc['n_samples']}")
```

Distributions are configured in `data/regions/{region}/uncertainty.yaml`. You can also pass custom distributions via `uncertainty_config`:

```python
mc = run_monte_carlo(
    formation_id="ncs_johansen",
    region="norway-ncs",
    n_samples=500,
    uncertainty_config={
        "permeability_md": {
            "distribution": "lognormal",
            "relative": True,
            "mean": 0.0,
            "sigma": 0.5,
            "min": 0.2,
            "max": 5.0,
        },
    },
)
```

### Supply Curve

Rank all formations in a region by FYBE:

```python
from ccs_costs.analysis import run_supply_curve

sc = run_supply_curve(region="norway-ncs", injection_rate_mtpa=3.0)

print(f"Region: {sc['region']}")
print(f"Evaluated: {sc['summary']['evaluated']}/{sc['summary']['total']}")
print(f"FYBE range: {sc['summary']['fybe_min']:.2f} - {sc['summary']['fybe_max']:.2f}")
print()
for f in sc["formations"]:
    if f.get("fybe") is not None:
        print(f"  {f['formation_name']}: FYBE={f['fybe']:.2f}, wells={f['well_count']}")
    else:
        print(f"  {f['formation_name']}: FAILED - {f.get('error', 'unknown')}")
```
