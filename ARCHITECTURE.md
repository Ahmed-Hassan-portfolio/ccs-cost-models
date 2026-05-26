# Architecture

## Components

```
+----------------------+      +----------------------+
|   FastMCP server     |      |   Streamlit UI       |
|   (server.py)        |      |   (app/)             |
|   10 MCP tools       |      |   3 pages            |
+----------+-----------+      +-----------+----------+
           |                              |
           +---------------+--------------+
                           |
                   +-------v--------+
                   |  scenario.py   |    end-to-end orchestrator
                   |  evaluate_     |    (replaces NETL Eval_Form VBA macro)
                   |  scenario()    |
                   +-------+--------+
                           |
       +---------+---------+---------+----------+
       |         |         |         |          |
   +---v---+ +---v---+ +---v---+ +---v---+  +---v---+
   |thermo | | geo   | | costs | |finance|  |config |
   |       | |       | |       | |       |  |       |
   +---+---+ +---+---+ +---+---+ +---+---+  +---+---+
       |         |         |         |          |
       v         v         v         v          v
   CO2/brine  Storage   Drilling   85-yr     Region
   Duan EOS   capacity  Pipeline   cashflow  YAML +
              Plume     Platform   Tax       formations
              Wells     Monitor    FYBE      JSON
              Schedule  Regulator  solver

                              +----------+
                              | history  |  SQLite scenario log
                              | (sqlite) |  (config + results as JSON)
                              +----------+
```

## Data flow (single FYBE evaluation)

1. **Input** — `ScenarioConfig(formation_id, region, injection_rate_tpa, ...)`
2. **Config load** — `config.py:load_region()` aggregates YAML + JSON for the region. Cached.
3. **Thermodynamics** — `thermo/co2.py` (Duan 1992) and `thermo/brine.py` compute density/viscosity at reservoir P, T. `thermo/multiflash.py` is an optional upgrade path; the engine works without it.
4. **Geological engine** — `geo/` derives storage capacity (Goodman 2011), CO2 plume area (radial Darcy), injectivity (Valluri), and the resulting active + spare well count.
5. **Cost modules** — `costs/` produces a `CostItem` catalog: drilling (NETL QUE\$TOR regression for US-GOA; IEAGHG 2005/2 regression for NCS), pipeline (NETL or Knoope), platform/subsea (water-depth dependent), monitoring (area-scaled), regulatory, decommissioning.
6. **Financial model** — `finance/` builds the 85-year cashflow (construction + injection + PISC), applies tax + depreciation + escalation, and `finance/solver.py` finds the FYBE via `scipy.optimize.brentq` on NPV = 0.
7. **Output** — `ScenarioResults` with FYBE in base-year and current-year dollars, cost breakdown, and a few dozen intermediate values. Optionally logged to SQLite (`history.py`).

## Key design decisions

- **Region as data, not code.** Each region is a directory under `data/regions/<id>/` with 5 YAML files + 1 JSON. Adding a new region means adding a directory, not editing the engine.
- **Module-level caches over global state.** `_REGION_CACHE` in `config.py` keeps deterministic loads fast across hundreds of formations in a supply curve.
- **Pydantic v2 boundary objects, plain functions inside.** `ScenarioConfig`, `RegionConfig`, `FormationProperties`, `ScenarioResults` use Pydantic for validation at module boundaries. Inside each module, the math is plain functions on floats and dataclasses — easier to test, no model-validation overhead in hot loops.
- **FYBE solver isolated.** `finance/solver.py:solve_fybe()` only depends on the cashflow construction and `brentq` — no knowledge of geology or costs. Cashflow construction takes `RevenueStreams`, `FinancialParams`, and a `CostItem` list and is region-agnostic.
- **Multiflash is optional.** `thermo/multiflash.py` calls a local MCP server for rigorous Span-Wagner CO2 density when available; on any failure (server down, `httpx` not installed) it silently falls back to the built-in Duan EOS.
- **History is best-effort.** `server.py` wraps `history.save_scenario()` in try/except so a failed SQLite write never poisons a tool response.
- **Tests run without internet, licenses, or external services.** No Multiflash, no MCP, no API keys required for the suite.

## What's NOT here (in this portfolio mirror)

- Reference NETL `.xlsm` files — link upstream in README.
- Raw research data (Sodir, SSB, PyPSA, Northern Lights ingest).
- Internal ETL scripts (`scripts/`).
- Internal planning and review notes.
