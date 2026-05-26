# Limitations, Safety, and Tool-Use Boundaries

This is a portfolio / research project. Numbers it produces are screening-
level (AACE Class 5, roughly ±40–60% on total cost). They are not
investment advice, not a safety basis, and not an operational decision
record. Any use beyond exploration or methodology study requires
independent engineering review and site-specific data.

A longer internal limitations register lives at
[`data/reference/model_limitations.md`](data/reference/model_limitations.md).
This file is the public-facing summary.

## What this engine is

A deterministic cost calculator for offshore CO2 storage. It re-implements
the modelling chain of NETL `CO2_S_COM_Offshore v1.1` (US Gulf of America)
and adds an alternative branch for the Norwegian Continental Shelf using
the IEAGHG 2005/2 drilling regression and Sodir CO2 Storage Atlas geology.
It exposes typed Python and MCP entry points and writes its scenario
results to a local SQLite history file.

## What this engine is *not*

- Not a Front-End Engineering Design (FEED) tool.
- Not a Final Investment Decision (FID) input.
- Not a safety basis. Wellbore integrity, plume containment, CO2 transport
  HSE, and emergency response are all outside scope.
- Not a regulatory submission. Subpart RR / EU MRV calculations here are
  illustrative.
- Not a substitute for vendor quotes. Drilling, subsea, and platform
  numbers are public-domain regressions, not contract pricing.

## Calibration boundaries

- The US-GOA branch is calibrated to NETL Formation 1241_1 (Chandeleur
  Area). For other formations the engine falls back to Formation 1
  drilling defaults — see the per-formation note below.
- The NCS branch uses the IEAGHG 2005/2 European drilling regression with
  an indicative escalation factor; this produces drilling costs roughly
  40–70% below Northern Lights actual contract values.
- CEPCI is used as the escalation proxy. CEPCI is not offshore-specific
  and is known to under-track offshore inflation.
- Storage coefficients come from IEAGHG 2009/12 lithology / depositional-
  environment / structure-type lookups, not formation-specific simulation.

## Per-formation drilling costs

The optional file `data/netl-extracted/netl_formation_results.json` would
carry per-formation QUE$TOR-regression outputs that vary drilling cost
with depth. That file is a derived product we do not redistribute. With
the file missing, `NETLDrillingRegression(formation_id=...)` silently
falls back to the Formation 1 (1241_1) defaults for every formation, and
the corresponding tests for cross-formation differentiation are marked
skipped (`tests/test_costs/test_drilling.py::TestNETLPerFormationCosts`).

This means: cross-formation FYBE differences in this portfolio mirror are
driven by geology (depth → CO2 density, area → plume, permeability →
injectivity, structure type → storage coefficient), corrective action
well counts, and pipeline distance — *not* by depth-dependent drilling
costs. Treat the supply-curve example as a methodology demonstration, not
a calibrated forecast.

## Tool-use safety (MCP)

The MCP server exposes 10 read-only calculator tools (no file writes
outside the local scenario history SQLite, no network calls, no
shell execution). When an LLM agent is wired to these tools, observe:

- **Input validation.** Every tool argument is bound to a Pydantic schema
  with units in the parameter name. Reject silently-coerced strings and
  log unrecognised arguments.
- **Bounded calculation.** Each call returns a single dict with
  pre-defined keys; an agent should never accept additional fields from
  the tool output as authoritative.
- **Trust boundary.** Treat tool results the same as you would treat a
  spreadsheet output: numbers with provenance and a known accuracy band.
  Do not pass them into safety, environmental, or financial decisions
  without independent engineering review.
- **Prompt-injection.** None of the tools execute or interpret text in
  the natural-language sense; their behaviour is determined by the typed
  arguments. Treat any free-text fields (notes, formation names) as
  display strings, not instructions.
- **Human escalation.** When a tool result drives an external action
  (procurement, regulatory submission, public communication), require
  human confirmation before that action. The MCP layer does not include
  any escalation policy of its own.

## Data and license boundaries

- No vendor binaries are bundled (NETL `.xlsm`, Multiflash, etc.); see
  [DATA_SOURCES.md](DATA_SOURCES.md) for upstream links.
- No proprietary cost data is shipped. The drilling, pipeline, and
  monitoring numbers here come from public reports (NETL, IEAGHG, Sodir,
  NLOD-2.0 Norway licensed data, peer-reviewed papers).

## Reproducibility

The repo runs end-to-end with `pip install -e ".[dev]"` and `pytest`
(240 passed, 2 skipped — see README). All inputs are local YAML/JSON.
No internet access, API keys, or vendor licences are required.
