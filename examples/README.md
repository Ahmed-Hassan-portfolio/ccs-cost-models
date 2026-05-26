# Examples

Three minimal runnable scripts. All inputs are public-domain formation
properties shipped with the repo (`data/regions/`), so the examples work
out-of-the-box after `pip install -e ".[dev]"`.

| Script | What it shows | Expected output |
|---|---|---|
| `01_evaluate_us_goa.py` | End-to-end FYBE for the NETL default formation `1241_1` | FYBE ~$25.34/t in 2008$ (~$72.20/t in 2024$) |
| `02_compare_formations.py` | Cost sweep across 5 US-GOA formations, sorted by FYBE | Small supply-curve table |
| `03_co2_properties.py` | Just the Duan 1992 EOS — density and viscosity at 4 reservoir conditions | NIST-comparable CO2 properties |

## Run them

```bash
python examples/01_evaluate_us_goa.py
python examples/02_compare_formations.py
python examples/03_co2_properties.py
```

## Where the data comes from

- `data/regions/us-goa/formations.json` — 117 Gulf of America saline formations
  extracted from NETL `CO2_S_COM_Offshore v1.1` (BSD-3 upstream).
- `data/regions/norway-ncs/formations.json` — 14 Norwegian Continental Shelf
  formations from the Sodir CO2 Storage Atlas (NLOD 2.0).
- `data/netl-extracted/escalation_indices.json` — CEPCI-based cost escalation
  factors used to roll 2008$ values to current-year dollars.
