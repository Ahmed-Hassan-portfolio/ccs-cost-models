# CCS Cost Model -- Limitations and Disclaimer

## MANDATORY DISCLAIMER

**This model produces AACE Class 5 cost estimates with accuracy of +/-50% (or wider for some components).** It is intended for:

- Screening-level comparisons between storage sites
- Understanding cost drivers and sensitivities
- Academic research and methodology development
- Early-stage portfolio assessment

**This model is NOT suitable for:**

- Final Investment Decisions (FID)
- Funding applications or grant proposals requiring bankable estimates
- Contract negotiations or procurement pricing
- Regulatory compliance cost submissions
- Insurance or financial guarantee calculations

Any use of model outputs for financial commitments without independent engineering review and site-specific data would be inappropriate and potentially misleading.

---

## Accuracy Classification

| Module | Accuracy | AACE Class | Key Limitation |
|--------|----------|------------|----------------|
| Pipeline CAPEX | +/-35-50% | 5 | FERC labor != NCS labor |
| Pipeline hydraulics | +/-5% | 2 | Physics-based (reliable) |
| Compression/pumping | +/-15-20% | 3-4 | Equipment scaling uncertainty |
| Well cost (SBBU + NCS rates) | +/-35-50% | 5 | Day rate and drilling time variance |
| Subsea infrastructure | +/-50-80% | 5 | n=1 project + n=1 paper |
| Monitoring costs | +/-40-60% | 5 | Grey literature only |
| Financial model | +/-10-15% | 3 | Model mature, inputs uncertain |
| Ship transport | +/-30-50% | 5 | Charter rate volatility, R-squared = 0.70-0.72 |
| **Total storage cost** | **+/-40-60%** | **5** | **Correlated errors compound** |
| **FYBE (EUR/t)** | **+/-35-50%** | **5** | **Dominated by well + infrastructure** |

---

## What This Model Cannot Do

### 1. No CO2 Capture Costs

The model covers transport and storage only. Capture costs (which dominate the CCS chain at 50-80% of total) are treated as a boundary condition. Users must source capture costs from separate models (e.g., IECM, IEAGHG cost curves).

### 2. No Onshore Storage

The model is designed for offshore Norwegian Continental Shelf (NCS) saline aquifer storage. Onshore storage has fundamentally different cost drivers (land acquisition, public acceptance, shallower wells, no subsea equipment). Extending to onshore would require a separate calibration effort.

### 3. No Depleted Oil/Gas Field Storage

The model focuses on saline aquifer storage. Depleted fields have different characteristics: existing wells (re-entry vs. new drill), known reservoir properties (less characterization needed), existing infrastructure (possible reuse), and different regulatory frameworks.

### 4. No Multi-User Hub Infrastructure

The model handles single-user, point-to-point transport and storage. Hub-and-spoke networks (e.g., Northern Lights as an open-access hub) involve shared infrastructure economics, capacity allocation, and scheduling that require separate optimization models.

### 5. No Geological Surprise

The model assumes reservoir properties are known from characterization data. It cannot predict:
- Compartmentalization discovered during injection
- Injectivity loss due to fines migration or geochemical reactions
- Unexpected faults or seal integrity issues
- Pressure interference between wells

These risks can add 50-200% to project costs and are the primary reason for the wide accuracy band.

### 6. Cannot Predict Individual Well Costs

Due to the inherent variability of drilling operations (R-squared approximately 0.06 for injection well duration vs. TVD), the model provides portfolio-average estimates, not individual well predictions. The 95% prediction interval for a single well spans roughly 3-10x the point estimate.

### 7. No Real-Time Market Updates

The model uses static cost data (CEPCI-escalated to EUR 2024 basis). Actual costs fluctuate with:
- Rig market conditions (day rates vary 2-5x over cycles)
- Steel prices (volatile, affected by trade policy)
- Subsea equipment backlogs (currently 18-24 months)
- Currency exchange rates

### 8. No Project Execution Risk

The model does not account for:
- Contractor availability
- Weather window constraints
- Supply chain disruptions
- Regulatory approval delays
- Community/stakeholder engagement costs

### 9. No Vessel Market Competition

NCS vessel markets are shared between petroleum, offshore wind, and decommissioning sectors. The model's day rates and charter rates do not account for market competition effects that can significantly affect availability and pricing.

### 10. Limited Calibration Data

The model is calibrated against a small number of real CCS projects:
- **Wells**: 5 NCS CO2 wells (Sleipner, Snohvit x2, Northern Lights x2)
- **Pipelines**: 2 NCS CO2 pipelines (Snohvit, Northern Lights)
- **Subsea**: 1 project (Northern Lights) + 1 academic study (Olivan 2024)
- **Monitoring**: Grey literature only (ACTOM toolbox, NETL parameterization)

As more CCS projects are completed and cost data becomes available, the model should be recalibrated.

---

## Key Data Limitations

### FERC Labor Costs are Not NCS Labor Costs

The Knoope 2014 pipeline model uses US FERC-derived labor productivity data. NCS labor is 1.5-2.0x more expensive due to offshore regulations, union agreements, and higher cost of living. The model applies a 1.5x labor factor as default, but this is an estimate with HIGH uncertainty (assumption #3 in the assumptions register).

### CEPCI is Not Offshore-Specific

The Chemical Engineering Plant Cost Index (CEPCI) tracks chemical process plant costs, not offshore construction. The offshore-specific Upstream Capital Cost Index (UCCI) is proprietary. The model uses CEPCI with a Euro location factor (1.20) and NCS offshore premium (1.15) as proxies, introducing additional uncertainty.

### Single-Source Subsea Costs

Subsea infrastructure costs are derived from a single project (Northern Lights, NOK 200M/system) and a single academic study (Olivan 2024). These costs have +/-50-80% uncertainty and are highly project-specific.

---

## Recommended Use Protocol

1. **Always report ranges**, not point estimates. Use P10/P50/P90 from Monte Carlo analysis.
2. **State the AACE Class 5 accuracy** (+/-50%) prominently in any presentation or document.
3. **Compare scenarios** rather than presenting absolute costs. Relative ranking is more reliable than absolute values.
4. **Run sensitivity analysis** on HIGH-risk assumptions (assumptions #3, #4, #9 in the register) before drawing conclusions.
5. **Cross-check** against published benchmarks: ZEP Case 6 (14 EUR/t), IEA Europe (30-60 USD/t), Northern Lights actuals.
6. **Update calibration** as new CCS project data becomes available.
