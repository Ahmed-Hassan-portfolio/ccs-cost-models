# Agent Tool Use

This page shows how an LLM agent should call the MCP tools shipped by the
FastMCP server (`ccs_costs.server`), what the responses look like, how
each tool behaves on bad input, and how to interpret uncertainty before
the answer leaves the agent. All examples below are reproduced verbatim
from the engine — they are not mock data.

The MCP server exposes 10 tools. Three are shown here. The full list is
in [`docs/api-reference.md`](../docs/api-reference.md).

---

## Example 1 — `estimate_storage_cost`

Single-formation FYBE estimate. This is the most common entry point for
an agent answering "how expensive is CO2 storage at formation X?".

### Call

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

### Response (exact engine output)

```json
{
  "formation_id": "1241_1",
  "formation_name": "PL_A1",
  "region": "us-goa",
  "fybe": 25.76,
  "fybe_current_year": 73.41,
  "fybe_interpretation": "Gross break-even storage fee (no revenue credits). This is the minimum fee a storage operator must charge to break even. Comparable to published storage cost estimates (e.g., Northern Lights EUR 30-60/t).",
  "n_injection_wells": 5,
  "n_monitoring_wells": 24,
  "pipeline_diameter_inches": 12.0,
  "pipeline_length_km": 66.9,
  "total_capex": 520663417,
  "total_opex": 1214197945,
  "total_co2_stored_mt": 120.0,
  "co2_density_kgm3": 577.9,
  "storage_coefficient": 0.0593,
  "currency": "USD",
  "base_year": 2008
}
```

### How an agent should interpret this

- The `fybe` field is a single point estimate, AACE Class 5 (±40–60 %).
  Do **not** present it as a precise number. Round to nearest USD/t and
  pair with the `fybe_interpretation` string and an uncertainty band
  before answering the user.
- `base_year` is 2008; `fybe_current_year` is escalated using the
  CEPCI table. If the user is asking about *today's* cost, use
  `fybe_current_year`; if they are reconciling against NETL or
  another 2008-dollar number, use `fybe`.
- For comparisons across formations, prefer the supply-curve tool (see
  Example 3) over many separate `estimate_storage_cost` calls.

---

## Example 2 — `co2_properties`

Pure thermodynamic lookup. No region needed.

### Call

```json
{
  "tool": "co2_properties",
  "arguments": {
    "pressure_mpa": 15.0,
    "temperature_c": 60.0
  }
}
```

### Response (exact engine output)

```json
{
  "pressure_mpa": 15.0,
  "temperature_c": 60.0,
  "density_kgm3": 610.95,
  "viscosity_pas": 4.683e-05,
  "compressibility_z": 0.3901,
  "method": "duan"
}
```

### How an agent should interpret this

- Duan 1992 density is within ~1 % of NIST Webbook across 5–40 MPa and
  4–150 °C; outside that envelope (or near the critical point) it can
  drift several percent. If the agent is asked about a near-critical
  point, hedge accordingly.
- A `viscosity_pas` value below ~1e-5 or above ~1e-4 is a sign the
  caller has likely sent gaseous or two-phase conditions; the underlying
  function may extrapolate. Cross-check with the published phase
  diagram before quoting.

---

## Example 3 — bad-input behaviour

The engine validates units and ranges at module boundaries and raises
clear errors rather than silently coercing inputs. Agents should
surface these messages to the user, not swallow them.

### Bad pressure

```python
co2_density(pressure_mpa=-5.0, temperature_c=60)
# ValueError: Pressure must be > 0.0 MPa, got -5
```

### Unknown formation

```json
{
  "tool": "estimate_storage_cost",
  "arguments": {
    "formation": "nonexistent",
    "region": "us-goa"
  }
}
```

Response (exception, surfaced through the MCP error channel):

```text
ValueError: Formation 'nonexistent' not found in region 'us-goa'.
Available IDs: ['1241_1', '1241_2', '1241_3', '1241_4', '1261_1',
'1261_2', '1261_3', '1261_4', '1261_5', '1261_6'] ... (117 total)
```

### Recommended agent behaviour

- On any tool error, **stop the action chain** rather than retrying
  with a guessed value. Ask the user to clarify or pick from a listed
  formation.
- Use `list_regions` and `list_formations` to enumerate valid inputs
  before constructing a deeper query.

---

## Interpreting uncertainty

Every estimate in this engine carries an AACE Class 5 accuracy band
(roughly ±40–60 % on total cost) — see
[LIMITATIONS.md](../LIMITATIONS.md). When an agent is asked something
like "what would CCS cost for formation X?", the answer should:

1. Quote the FYBE rounded to a single significant figure (or a USD/t
   range), not the raw float.
2. Mention the AACE class.
3. Note when the formation falls back to Formation 1 default drilling
   costs (any formation other than `1241_1` in `us-goa` — see
   LIMITATIONS.md).
4. Quote `fybe_interpretation` verbatim so the user understands whether
   revenue credits (EU ETS, 45Q, CO2 tax) are or are not included.

For ranked questions ("which formation is cheapest?"), prefer the
`compare_formations` or `run_supply_curve` tools so the relative
ordering is internally consistent.

---

## Human review boundary

These tools are calculators. They are **not** authority for:

- Final Investment Decisions
- Procurement or contract pricing
- Safety basis (wellbore integrity, plume containment, HSE)
- Regulatory submissions
- Public statements about a specific named project

If a tool result is feeding any of those downstream uses, an agent must
escalate to a human engineering reviewer before the action proceeds.
The MCP layer does not implement that escalation; the surrounding agent
framework must.
