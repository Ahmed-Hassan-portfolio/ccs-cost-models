# API Reference

This document covers the CCS Cost Estimation Engine's two main interfaces:

1. **MCP Tool Reference** -- for AI agents connecting via the Model Context Protocol
2. **Python API Reference** -- for human developers importing the library directly

---

## Section 1: MCP Tool Reference

The engine exposes 10 MCP tools via a FastMCP server. Start the server with:

```bash
ccs-cost-server
```

Tools are grouped into three categories: Core (4), Discovery (3), and Analysis (3).

---

### Core Tools

#### `estimate_storage_cost`

Estimate break-even CO2 storage cost (FYBE) for a formation. Runs the full calculation chain: thermodynamics, geology, costs, finance.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `formation` | `str` | *required* | Formation ID (e.g. `'1241_1'` for US-GOA, `'ncs_johansen'` for Norway-NCS) |
| `region` | `str` | *required* | Region identifier (e.g. `'us-goa'`, `'norway-ncs'`) |
| `injection_rate_mtpa` | `float` | `3.0` | CO2 injection rate in million tonnes per year |
| `operations_years` | `int \| None` | `None` | Override for injection period length (years) |
| `infrastructure` | `str \| None` | `None` | Override infrastructure model: `'platform_jacket'` or `'subsea_tieback'` |

**Return Schema:**

| Key | Type | Description |
|-----|------|-------------|
| `formation_id` | `str` | Formation identifier |
| `formation_name` | `str` | Human-readable formation name |
| `region` | `str` | Region used |
| `fybe` | `float` | Break-even CO2 price in base-year currency per tonne |
| `fybe_current_year` | `float` | FYBE escalated to project start year |
| `n_injection_wells` | `int` | Total injection wells (active + spare) |
| `n_monitoring_wells` | `int` | Monitoring well count |
| `pipeline_diameter_inches` | `float` | Nominal pipeline diameter |
| `pipeline_length_km` | `float` | Pipeline length |
| `total_capex` | `float` | Total capital expenditure (base year) |
| `total_opex` | `float` | Total operating expenditure (base year) |
| `total_co2_stored_mt` | `float` | Total CO2 stored over project lifetime (Mt) |
| `co2_density_kgm3` | `float` | CO2 density at reservoir conditions |
| `storage_coefficient` | `float` | Storage efficiency factor |
| `currency` | `str` | Currency code (USD, NOK, EUR) |
| `base_year` | `int` | Cost base year |

**Example Request:**

```json
{
  "formation": "1241_1",
  "region": "us-goa",
  "injection_rate_mtpa": 4.0
}
```

**Example Response:**

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
  "co2_density_kgm3": 661.4,
  "storage_coefficient": 0.0218,
  "currency": "USD",
  "base_year": 2008
}
```

Results are auto-saved to SQLite scenario history on each call.

---

#### `co2_properties`

Get CO2 thermophysical properties at given conditions. Pure thermodynamic lookup -- no region parameter needed.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `pressure_mpa` | `float` | *required* | Pressure in MPa |
| `temperature_c` | `float` | *required* | Temperature in degrees Celsius |
| `method` | `str` | `"duan"` | EOS method: `'duan'` or `'peng-robinson'` |

**Return Schema:**

| Key | Type | Description |
|-----|------|-------------|
| `pressure_mpa` | `float` | Input pressure |
| `temperature_c` | `float` | Input temperature |
| `density_kgm3` | `float` | CO2 density (kg/m3) |
| `viscosity_pas` | `float` | CO2 dynamic viscosity (Pa-s) |
| `compressibility_z` | `float` | CO2 compressibility factor Z |
| `method` | `str` | EOS method used |

**Example Request:**

```json
{
  "pressure_mpa": 15.0,
  "temperature_c": 60.0
}
```

**Example Response:**

```json
{
  "pressure_mpa": 15.0,
  "temperature_c": 60.0,
  "density_kgm3": 616.2341,
  "viscosity_pas": 4.56e-05,
  "compressibility_z": 0.389412,
  "method": "duan"
}
```

---

#### `calculate_pipeline`

Size a CO2 pipeline and estimate costs. Computes CO2 properties at pipeline conditions, then determines minimum pipeline diameter using Darcy-Weisbach hydraulics with Colebrook-White friction.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `flow_rate_mtpa` | `float` | *required* | CO2 flow rate in million tonnes per year |
| `distance_km` | `float` | *required* | Pipeline length in km |
| `region` | `str` | *required* | Region identifier for cost model selection |
| `inlet_pressure_mpa` | `float` | `15.0` | Pipeline inlet pressure (MPa) |
| `outlet_pressure_mpa` | `float` | `8.0` | Pipeline outlet pressure (MPa) |
| `temperature_c` | `float` | `4.0` | Pipeline temperature (Celsius) |

**Return Schema:**

| Key | Type | Description |
|-----|------|-------------|
| `diameter_inches` | `float` | Nominal standard pipe size (inches) |
| `diameter_min_inches` | `float` | Minimum hydraulic diameter (inches) |
| `velocity_ms` | `float` | CO2 flow velocity (m/s) |
| `flow_rate_mtpa` | `float` | Input flow rate |
| `distance_km` | `float` | Input distance |
| `co2_density_kgm3` | `float` | CO2 density at pipeline conditions |
| `region` | `str` | Region used |

**Example Request:**

```json
{
  "flow_rate_mtpa": 3.0,
  "distance_km": 100.0,
  "region": "norway-ncs",
  "temperature_c": 4.0
}
```

**Example Response:**

```json
{
  "diameter_inches": 12,
  "diameter_min_inches": 8.72,
  "velocity_ms": 1.234,
  "flow_rate_mtpa": 3.0,
  "distance_km": 100.0,
  "co2_density_kgm3": 958.3,
  "region": "norway-ncs"
}
```

---

#### `get_scenario_history`

Retrieve recent scenario results from the SQLite history database.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `region` | `str \| None` | `None` | Filter by region (optional) |
| `formation_id` | `str \| None` | `None` | Filter by formation ID (optional) |
| `limit` | `int` | `20` | Maximum results to return |

**Return Schema:**

Returns a list of scenario summaries. Each entry contains:

| Key | Type | Description |
|-----|------|-------------|
| `id` | `int` | Database row ID |
| `timestamp` | `str` | ISO 8601 timestamp |
| `region` | `str` | Region identifier |
| `formation_id` | `str` | Formation identifier |
| `fybe` | `float` | Break-even CO2 price |

**Example Request:**

```json
{
  "region": "us-goa",
  "limit": 5
}
```

---

### Discovery Tools

#### `list_regions`

List available regions with summary info.

**Parameters:** None.

**Return Schema:**

Returns a list of region summaries:

| Key | Type | Description |
|-----|------|-------------|
| `name` | `str` | Region identifier |
| `currency` | `str` | Currency code |
| `base_year` | `int` | Cost base year |
| `formation_count` | `int` | Number of formations available |

**Example Response:**

```json
[
  {"name": "us-goa", "currency": "USD", "base_year": 2008, "formation_count": 117},
  {"name": "norway-ncs", "currency": "NOK", "base_year": 2024, "formation_count": 14}
]
```

---

#### `list_formations`

List available formations in a region with key properties.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `region` | `str` | *required* | Region identifier (e.g. `'us-goa'`, `'norway-ncs'`) |

**Return Schema:**

Returns a list of formation property summaries:

| Key | Type | Description |
|-----|------|-------------|
| `id` | `str` | Formation identifier |
| `name` | `str` | Human-readable name |
| `depth_m` | `float` | Depth in meters |
| `porosity` | `float` | Porosity (fraction, 0-1) |
| `permeability_md` | `float` | Permeability in millidarcies |
| `thickness_m` | `float` | Formation thickness in meters |
| `water_depth_m` | `float` | Water depth in meters |

**Example Request:**

```json
{
  "region": "norway-ncs"
}
```

---

#### `compare_formations`

Compare storage costs across multiple formations, sorted by FYBE (cheapest first).

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `formations` | `list[str]` | *required* | List of formation IDs to compare |
| `region` | `str` | *required* | Region identifier |
| `injection_rate_mtpa` | `float` | `3.0` | CO2 injection rate in Mt/yr |

**Return Schema:**

Returns a list of compact result dicts (same schema as `estimate_storage_cost`), sorted by `fybe` ascending. Failed formations appear at the end with `fybe: Infinity` and an `error` field.

**Example Request:**

```json
{
  "formations": ["ncs_johansen", "utsira_south", "sognefjord"],
  "region": "norway-ncs",
  "injection_rate_mtpa": 3.0
}
```

---

### Analysis Tools

#### `run_sensitivity`

Sensitivity analysis on formation economics. Two modes of operation:

- **One-way** (`parameter` specified): sweeps a single parameter across its range
- **Tornado** (`parameter` omitted): sweeps all parameters and ranks by impact

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `formation` | `str` | *required* | Formation ID |
| `region` | `str` | *required* | Region identifier |
| `parameter_ranges` | `dict` | *required* | Dict of `{param_name: [min_value, max_value]}` |
| `parameter` | `str \| None` | `None` | If specified, runs one-way for this parameter only. If omitted, runs tornado across all. |
| `steps` | `int` | `7` | Number of sweep steps per parameter |

**Supported parameters:** `porosity`, `permeability_md`, `depth_m`, `thickness_m`, `area_km2`, `net_to_gross`, `temperature_c`, `pressure_mpa`, `injection_rate_mtpa`, `operations_years`, `ets_price`, `co2_tax_rate`. Short aliases without unit suffix also accepted (e.g. `permeability`, `depth`).

**Return Schema (One-way):**

```json
{
  "mode": "one_way",
  "formation": "1241_1",
  "region": "us-goa",
  "parameter": "permeability_md",
  "steps": [
    {"param_value": 50.0, "fybe": 28.42},
    {"param_value": 100.0, "fybe": 25.76},
    {"param_value": 150.0, "fybe": 24.31}
  ]
}
```

**Return Schema (Tornado):**

```json
{
  "mode": "tornado",
  "formation": "1241_1",
  "region": "us-goa",
  "parameters": [
    {
      "parameter": "permeability_md",
      "swing": 8.52,
      "fybe_at_low": 30.42,
      "fybe_base": 25.76,
      "fybe_at_high": 21.90
    }
  ]
}
```

**Example Request (Tornado):**

```json
{
  "formation": "1241_1",
  "region": "us-goa",
  "parameter_ranges": {
    "permeability_md": [50, 200],
    "distance_from_shore_km": [20, 100]
  }
}
```

---

#### `run_supply_curve`

Evaluate all formations in a region and rank by FYBE (cheapest first). Failed formations are appended at the end with `fybe: null` and an error field -- nothing is silently dropped.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `region` | `str` | *required* | Region identifier |
| `injection_rate_mtpa` | `float` | *required* | Target CO2 injection rate in Mt/yr |

**Return Schema:**

| Key | Type | Description |
|-----|------|-------------|
| `region` | `str` | Region evaluated |
| `injection_rate_mtpa` | `float` | Injection rate used |
| `formations` | `list[dict]` | Results sorted by fybe ascending, failures at end |
| `summary` | `dict` | `{total, evaluated, failed, fybe_min, fybe_max, fybe_median}` |

Per-formation entry:

| Key | Type | Description |
|-----|------|-------------|
| `formation_id` | `str` | Formation identifier |
| `formation_name` | `str` | Human-readable name |
| `fybe` | `float \| null` | Break-even price (null if failed) |
| `well_count` | `int` | Injection well count |
| `capex_musd` | `float` | Total CAPEX in millions |
| `opex_musd` | `float` | Total OPEX in millions |
| `storage_capacity_gt` | `float` | Total storage capacity in Gt |

**Example Request:**

```json
{
  "region": "norway-ncs",
  "injection_rate_mtpa": 3.0
}
```

---

#### `run_monte_carlo`

Probabilistic FYBE analysis via Monte Carlo simulation. Samples parameter distributions from `data/regions/{region}/uncertainty.yaml`. Uses multiprocessing (`ProcessPoolExecutor`) for performance.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `formation` | `str` | *required* | Formation ID |
| `region` | `str` | *required* | Region identifier |
| `n_samples` | `int` | `1000` | Number of Monte Carlo samples |
| `uncertainty_config` | `dict \| None` | `None` | Optional per-parameter distribution overrides |
| `seed` | `int` | `42` | RNG seed for reproducibility |

**Return Schema:**

| Key | Type | Description |
|-----|------|-------------|
| `p10` | `float` | 10th percentile FYBE |
| `p50` | `float` | 50th percentile (median) FYBE |
| `p90` | `float` | 90th percentile FYBE |
| `mean` | `float` | Mean FYBE |
| `std_dev` | `float` | Standard deviation |
| `min` | `float` | Minimum FYBE |
| `max` | `float` | Maximum FYBE |
| `n_success` | `int` | Number of successful evaluations |
| `n_failed` | `int` | Number of failed evaluations |
| `seed` | `int` | RNG seed used |
| `formation_id` | `str` | Formation evaluated |
| `region` | `str` | Region used |
| `n_samples` | `int` | Total samples requested |

**Example Request:**

```json
{
  "formation": "ncs_johansen",
  "region": "norway-ncs",
  "n_samples": 500,
  "seed": 42
}
```

**Example Response:**

```json
{
  "p10": 12.5,
  "p50": 18.3,
  "p90": 28.7,
  "mean": 19.1,
  "std_dev": 5.4,
  "min": 8.2,
  "max": 42.1,
  "n_success": 498,
  "n_failed": 2,
  "seed": 42,
  "formation_id": "ncs_johansen",
  "region": "norway-ncs",
  "n_samples": 500
}
```

---

## Section 2: Python API Reference

For developers importing the library directly. Install with:

```bash
pip install -e .
```

---

### `ccs_costs.scenario.evaluate_scenario`

Full scenario evaluation -- the central integration point. Wires all engine modules end-to-end: thermodynamics, geology, costs, finance. Maps to the NETL VBA `Eval_Form` macro.

```python
from ccs_costs.scenario import ScenarioConfig, evaluate_scenario

config = ScenarioConfig(
    formation_id="1241_1",
    region="us-goa",
    injection_rate_tpa=4_000_000,
)

result = evaluate_scenario(config)
print(f"FYBE: ${result.fybe:.2f}/t ({result.base_year}$)")
print(f"FYBE: ${result.fybe_current_year:.2f}/t ({result.config.region} current year)")
print(f"Wells: {result.n_injection_wells}, Pipeline: {result.pipeline_diameter_inches}\"")
```

**Signature:**

```python
def evaluate_scenario(config: ScenarioConfig) -> ScenarioResults
```

**Args:**
- `config` (`ScenarioConfig`): Master input configuration.

**Returns:** `ScenarioResults` with FYBE and all intermediate values.

**Raises:** `ValueError` if formation not found or injection is infeasible.

---

### `ccs_costs.scenario.ScenarioConfig`

Master input configuration (Pydantic `BaseModel`). All inputs needed to run the full calculation chain.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `formation_id` | `str` | *required* | Formation ID from the region's `formations.json` |
| `region` | `str` | *required* | Region identifier (e.g. `'us-goa'`, `'norway-ncs'`) |
| `injection_rate_tpa` | `float` | `4_000_000` | CO2 injection rate in tonnes per year |
| `capacity_factor` | `float` | `0.85` | Well utilization factor |
| `max_rate_per_well_tpd` | `float` | `3660` | Maximum injection rate per well (tonnes/day) |
| `storage_coefficient_method` | `str` | `"lookup"` | Storage coefficient method |
| `storage_coefficient_probability` | `str` | `"P50"` | Probability level: `P10`, `P50`, `P90` |
| `injectivity_method` | `str` | `"valluri"` | Injectivity method: `'valluri'` or `'zhou'` |
| `pipeline_distance_km` | `float \| None` | `None` | Override pipeline distance (else uses formation value) |
| `infrastructure_model` | `str \| None` | `None` | Override: `'platform_jacket'` or `'subsea_tieback'` |
| `operations_years` | `int \| None` | `None` | Override operations period (years) |
| `co2_property_method` | `str` | `"duan"` | EOS method: `'duan'` or `'peng-robinson'` |
| `formation_overrides` | `dict \| None` | `None` | Override formation properties for sensitivity/MC |
| `economic_overrides` | `dict \| None` | `None` | Override economic params (e.g. `ets_price`, `co2_tax_rate`) |

---

### `ccs_costs.scenario.ScenarioResults`

Master output from a scenario evaluation (Pydantic `BaseModel`).

| Field | Type | Description |
|-------|------|-------------|
| `fybe` | `float` | Break-even CO2 price (base year $/t) |
| `fybe_current_year` | `float` | Escalated to current year $/t |
| `npv` | `float` | Net present value at FYBE price |
| `irr` | `float \| None` | Internal rate of return (if computable) |
| `formation_id` | `str` | Formation evaluated |
| `formation_name` | `str` | Formation name |
| `region` | `str` | Region used |
| `co2_density_kgm3` | `float` | CO2 density at reservoir conditions |
| `storage_coefficient` | `float` | Storage efficiency factor |
| `plume_area_km2` | `float` | CO2 plume footprint |
| `n_injection_wells` | `int` | Total injection wells |
| `n_monitoring_wells` | `int` | Monitoring well count |
| `pipeline_diameter_inches` | `float` | Nominal pipeline diameter |
| `pipeline_length_km` | `float` | Pipeline length |
| `total_capex` | `float` | Total capital expenditure (base year) |
| `total_opex` | `float` | Total operating expenditure (base year) |
| `total_co2_stored_mt` | `float` | Total CO2 stored (Mt) |
| `project_duration_years` | `int` | Total project duration |
| `currency` | `str` | Currency code |
| `base_year` | `int` | Cost base year |
| `timestamp` | `str` | ISO 8601 evaluation timestamp |
| `config` | `ScenarioConfig` | Input config for reproducibility |

**Method:** `to_compact_dict() -> dict` -- returns a compact dict with ~16 key fields for comparison and serialization.

---

### `ccs_costs.config.load_region`

Load all configuration for a region from `data/regions/{region}/`.

```python
from ccs_costs.config import load_region

rc = load_region("norway-ncs")
print(f"Region: {rc.name}, Currency: {rc.currency}, Base year: {rc.base_year}")
print(f"Formations: {len(rc.formations)}")
print(f"Infrastructure: {rc.infrastructure_model.value}")
```

**Signature:**

```python
def load_region(region: str) -> RegionConfig
```

**Args:**
- `region` (`str`): Region identifier (e.g. `'us-goa'`, `'norway-ncs'`).

**Returns:** `RegionConfig` with all configuration loaded and validated. Results are cached.

**Raises:** `FileNotFoundError` if the region directory or required files don't exist.

---

### `ccs_costs.config.RegionConfig`

Complete region configuration (Pydantic `BaseModel`).

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Region identifier |
| `currency` | `str` | Currency code (USD, NOK, EUR) |
| `base_year` | `int` | Base cost year |
| `formations` | `dict[str, FormationProperties]` | Formation ID -> properties mapping |
| `costs_config` | `dict` | Raw costs.yaml data |
| `finance_config` | `dict` | Finance config (includes `TaxRegime`) |
| `monitoring_config` | `MonitoringUnitCosts` | From monitoring.yaml |
| `regulatory_config` | `RegulatoryConfig` | From regulatory.yaml |
| `timeline` | `ProjectTimeline` | Project schedule defaults |
| `infrastructure_model` | `InfrastructureModel` | Default infrastructure type |
| `drilling_config` | `dict` | Drilling parameters from costs.yaml |
| `escalation` | `EscalationConfig` | Cost escalation parameters |

---

### `ccs_costs.config.list_available_regions`

List available regions that have at least a `costs.yaml` file.

```python
from ccs_costs.config import list_available_regions

regions = list_available_regions()
# ['norway-ncs', 'us-goa']
```

**Signature:**

```python
def list_available_regions() -> list[str]
```

---

### `ccs_costs.costs.pipeline.pipeline_diameter`

Calculate pipeline diameter for CO2 transport using Darcy-Weisbach hydraulics.

```python
from ccs_costs.costs.pipeline import pipeline_diameter

result = pipeline_diameter(
    flow_rate_tpa=4_000_000,
    length_km=60.8,
    inlet_pressure_mpa=15.0,
    outlet_pressure_mpa=8.5,
    temperature_c=12.78,
    co2_density_kgm3=900.0,
    co2_viscosity_pas=6.0e-5,
)
print(f"Nominal diameter: {result['nominal_diameter_inches']}\"")
print(f"Min diameter: {result['min_diameter_inches']:.2f}\"")
```

**Signature:**

```python
def pipeline_diameter(
    flow_rate_tpa: float,
    length_km: float,
    inlet_pressure_mpa: float,
    outlet_pressure_mpa: float,
    temperature_c: float,
    co2_density_kgm3: float,
    co2_viscosity_pas: float,
    roughness_m: float = 4.6e-5,
    elevation_change_m: float = 0.0,
) -> dict
```

**Returns:** Dictionary with `min_diameter_m`, `min_diameter_inches`, `nominal_diameter_inches`, `reynolds_number`, `friction_factor_fanning`, `flow_rate_kgs`.

---

### `ccs_costs.finance.solver.solve_fybe`

Find the first-year break-even CO2 storage price (FYBE) where NPV = 0.

```python
from ccs_costs.finance.solver import solve_fybe

result = solve_fybe(
    cost_catalog=cost_catalog,
    schedule=schedule,
    financial_params=financial_params,
    tax_regime=tax_regime,
    escalation=escalation,
    revenue_streams=revenue_streams,  # Norwegian only
)
print(f"FYBE: ${result.fybe_base_year:.2f}/t ({result.base_year}$)")
print(f"FYBE: ${result.fybe_current_year:.2f}/t ({result.current_year}$)")
print(f"NPV at FYBE: ${result.npv:.0f}")
```

**Signature:**

```python
def solve_fybe(
    cost_catalog: CostCatalog,
    schedule: ProjectSchedule,
    financial_params: FinancialParams,
    tax_regime: TaxRegime,
    escalation: EscalationConfig,
    revenue_streams: RevenueStreams | None = None,
    price_range: tuple[float, float] = (0.0, 500.0),
    tolerance: float = 0.0001,
) -> FYBEResult
```

**Returns:** `FYBEResult` with `fybe_base_year`, `fybe_current_year`, `base_year`, `current_year`, `npv`, `total_capex`, `total_opex`, `lcoe`.

**Raises:** `ValueError` if solver cannot converge (no root in bracket).

The solver uses `scipy.optimize.brentq` for guaranteed convergence. For Norwegian scenarios with revenue streams (ETS credits, CO2 tax), the bracket auto-expands to negative prices if the project is profitable without a storage fee.

---

### `ccs_costs.analysis.run_one_way_sensitivity`

Sweep a single parameter across a range and return FYBE at each step.

```python
from ccs_costs.analysis import run_one_way_sensitivity

results = run_one_way_sensitivity(
    formation_id="1241_1",
    region="us-goa",
    parameter="permeability_md",
    min_value=50.0,
    max_value=200.0,
    steps=7,
)
for r in results:
    print(f"  k={r['param_value']:.0f} md -> FYBE=${r['fybe']:.2f}/t")
```

**Signature:**

```python
def run_one_way_sensitivity(
    formation_id: str,
    region: str,
    parameter: str,
    min_value: float,
    max_value: float,
    steps: int = 7,
) -> list[dict]
```

**Returns:** List of `{"param_value": float, "fybe": float | None, "error": str (optional)}`.

---

### `ccs_costs.analysis.run_tornado_sensitivity`

Sweep all parameters and rank by FYBE swing (largest impact first).

```python
from ccs_costs.analysis import run_tornado_sensitivity

tornado = run_tornado_sensitivity(
    formation_id="1241_1",
    region="us-goa",
    parameter_ranges={
        "permeability_md": [50, 200],
        "thickness_m": [50, 300],
        "distance_from_shore_km": [20, 100],
    },
    steps=3,
)
for entry in tornado:
    print(f"  {entry['parameter']}: swing={entry['swing']:.2f}")
```

**Signature:**

```python
def run_tornado_sensitivity(
    formation_id: str,
    region: str,
    parameter_ranges: dict[str, list[float]],
    steps: int = 7,
) -> list[dict]
```

**Returns:** List of `{"parameter", "swing", "fybe_at_low", "fybe_base", "fybe_at_high"}`, sorted by `swing` descending.

---

### `ccs_costs.analysis.run_monte_carlo`

Probabilistic FYBE analysis using Monte Carlo sampling with `ProcessPoolExecutor`.

```python
from ccs_costs.analysis import run_monte_carlo

mc = run_monte_carlo(
    formation_id="ncs_johansen",
    region="norway-ncs",
    n_samples=500,
    seed=42,
)
print(f"P10={mc['p10']:.1f}, P50={mc['p50']:.1f}, P90={mc['p90']:.1f}")
```

**Signature:**

```python
def run_monte_carlo(
    formation_id: str,
    region: str,
    n_samples: int = 1000,
    uncertainty_config: dict | None = None,
    seed: int = 42,
) -> dict
```

**Returns:** Dict with `p10`, `p50`, `p90`, `mean`, `std_dev`, `min`, `max`, `n_success`, `n_failed`, `seed`, `formation_id`, `region`, `n_samples`.

---

### `ccs_costs.analysis.run_supply_curve`

Evaluate all formations in a region and rank by FYBE (cheapest first).

```python
from ccs_costs.analysis import run_supply_curve

sc = run_supply_curve(region="norway-ncs", injection_rate_mtpa=3.0)
print(f"Evaluated: {sc['summary']['evaluated']}/{sc['summary']['total']}")
for f in sc["formations"][:5]:
    print(f"  {f['formation_name']}: FYBE={f['fybe']:.2f}")
```

**Signature:**

```python
def run_supply_curve(
    region: str,
    injection_rate_mtpa: float,
) -> dict
```

**Returns:** Dict with `region`, `injection_rate_mtpa`, `formations` (list sorted by fybe), and `summary` (`{total, evaluated, failed, fybe_min, fybe_max, fybe_median}`).
