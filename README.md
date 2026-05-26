# CCS Cost Models

This repo is a deterministic engineering-tool example: a Python rebuild of the NETL offshore CO2 storage cost workflow, exposed through both normal Python entry points and FastMCP tools.

I built it because LLM agents should not invent cost numbers. If an agent needs a storage-cost estimate, a sensitivity sweep, or a supply-curve sketch, it should call a typed calculator with known assumptions and limitations. This repository is that calculator for a narrow CCS storage-cost use case.

The model is useful as a transparent portfolio and methodology artifact. It is not a project sanctioning tool, not a safety basis, and not investment advice.

## What's technically interesting

- **Cross-checked port of an Excel/VBA model.** The US Gulf of America branch
  reproduces NETL `CO2_S_COM_Offshore v1.1` for Formation 1241_1 (Chandeleur
  Area): FYBE $25.76/t (2008$) vs NETL $25.34/t — $0.42/t / 1.7% deviation,
  with CAPEX/OPEX matching the NETL totals to within 1% (see
  `tests/test_integration/test_scenario.py`).
- **Two regions, one engine.** US Gulf of America (NETL-calibrated, USD/2008$)
  and Norwegian Continental Shelf (IEAGHG 2005/2 drilling regression + Sodir
  CO2 Storage Atlas geology, NOK/2024$) share the same thermo → geo → costs
  → finance pipeline. Region is data, not code.
- **CO2 thermodynamics from scratch.** Duan 1992 EOS implementation
  cross-checked against NIST Webbook density across 5–40 MPa, 4–150 °C,
  including the supercritical region where cubic EOSs degrade.
- **FYBE solver as NPV = 0 root-finding.** First-Year Break-Even price is the
  SciPy `brentq` root of the 85-year discounted cashflow (3-yr construction +
  30-yr injection + 50-yr post-injection), with tax, depreciation, escalation
  (CEPCI), and Norway-specific revenue streams handled in the cashflow
  builder.
- **MCP-native.** 10 deterministic tools (`estimate_storage_cost`,
  `run_supply_curve`, `run_monte_carlo`, `compare_formations`,
  `run_sensitivity`, `co2_properties`, `calculate_pipeline`, `list_regions`,
  `list_formations`, `get_scenario_history`) plus a Streamlit UI sit on top
  of the same engine. Designed so an LLM agent calls typed engineering
  tools instead of inventing numbers.

## Architecture

```
Formation ID + Region
        |
   Thermodynamics ----- CO2 + brine density / viscosity  (Duan 1992 EOS)
        |
   Geological Engine -- Storage capacity, plume area, injectivity, well count
        |
   Cost Modules ------- Drilling, pipeline, platform/subsea, monitoring,
        |               regulatory, decommissioning
   Financial Model ---- 85-year cashflow, tax, depreciation, escalation (CEPCI)
        |
   FYBE Solver -------- scipy.optimize.brentq -> NPV(price) = 0
        |
First-Year Break-Even storage price  ($/t or NOK/t)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for component-level detail.

## Stack

Python 3.12 · NumPy · SciPy · Pydantic v2 · PyYAML · FastMCP · pytest · Streamlit

## Try it

```bash
git clone <repo-url>
cd ccs-cost-models
pip install -e ".[dev]"
python examples/01_evaluate_us_goa.py     # FYBE for NETL default formation
python examples/02_compare_formations.py  # supply-curve sketch (5 formations)
python examples/03_co2_properties.py      # Duan 1992 EOS sanity check
pytest                                    # 240 passed, 2 skipped
streamlit run app/streamlit_app.py        # optional UI
```

The MCP server starts with `ccs-cost-server` (installed as a console script)
or `python -m ccs_costs`.

## Tests

```
240 passed, 2 skipped
```

The two skipped tests check per-formation drilling cost differentiation,
which depends on `data/netl-extracted/netl_formation_results.json` — a
derived QUE$TOR-regression product that we do not redistribute with this
portfolio mirror. Without it, the engine falls back to Formation 1
(1241_1) defaults for every formation, so cross-formation drilling
differences are scaled by depth-independent terms only. See
[LIMITATIONS.md](LIMITATIONS.md).

## Why this matters for agentic engineering

LLM agents working on industrial cost questions should call deterministic
engineering tools for capacity, plume, drilling, pipeline, and cashflow
math instead of guessing. This project exposes typed MCP tools so an agent
can estimate CCS storage cost, compare formations, run a Monte Carlo or
sensitivity sweep, and build a supply curve — each with explicit units,
input validation, and documented limitations. See
[examples/agent_tool_use.md](examples/agent_tool_use.md) for sample tool
calls and how to interpret the output safely.

## Status

Portfolio / research project maintained for demonstration and
reproducibility. Results are model estimates and not investment, safety,
or operational advice. See [LIMITATIONS.md](LIMITATIONS.md).

## Author and related work

This engine is written by Ahmed Hassan. The NCS drilling-time calibration
draws on first-author research: Hassan, Schei, Stanko & Sangesland (2024),
*Revolutionizing CCS Wells: Economically Feasible Design Innovations*,
EAGE Earthdoc, [doi:10.3997/2214-4609.202421179](https://doi.org/10.3997/2214-4609.202421179).
Other dependencies are cited in [DATA_SOURCES.md](DATA_SOURCES.md).

## Data sources and licensing

See [DATA_SOURCES.md](DATA_SOURCES.md) for the provenance, license, and
redistribution status of every dataset shipped in `data/`. Upstream NETL
`.xlsm` files are not redistributed — link in DATA_SOURCES.md.

## License

BSD-3-Clause — matches upstream NETL models (`CO2_S_COM_Offshore v1.1`,
BSD-3). See [LICENSE](LICENSE).
