"""Tests for pipeline hydraulic sizing and cost models.

Tests cover:
- CostItem/CostCatalog Pydantic data models
- Reynolds number calculation matching VBA Reyn_N
- Colebrook-White friction factor matching VBA FFF_Cole
- Pipeline minimum diameter (incompressible) matching VBA Dia_in_min
- Standard pipe size selection matching VBA Pipe_Size
- NETL default scenario: 12-inch pipeline for Formation 1
"""

from __future__ import annotations

import math

import pytest

# ============================================================================
# CostItem and CostCatalog model tests
# ============================================================================


class TestCostItem:
    """Tests for CostItem Pydantic model validation."""

    def test_cost_item_validates_with_all_fields(self):
        from ccs_costs.costs.catalog import CostClassification, CostItem, DepreciationCategory

        item = CostItem(
            id="PIPE-001",
            name="Offshore pipeline construction",
            category="pipeline",
            subcategory="construction",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PIPELINE,
            amount_base_year=206_369_911.0,
            base_year=2008,
            currency="USD",
            begin_year=3,
            end_year=3,
            recurrence="one-time",
            quantity=1.0,
            notes="NETL offshore pipeline CAPEX",
        )
        assert item.id == "PIPE-001"
        assert item.amount_base_year == 206_369_911.0
        assert item.classification == CostClassification.CAPITAL

    def test_cost_item_rejects_missing_required_fields(self):
        from ccs_costs.costs.catalog import CostItem

        with pytest.raises(Exception):  # ValidationError
            CostItem(
                id="PIPE-001",
                # missing required fields
            )


class TestCostCatalog:
    """Tests for CostCatalog aggregate model."""

    def _make_catalog(self):
        from ccs_costs.costs.catalog import (
            CostCatalog,
            CostClassification,
            CostItem,
            DepreciationCategory,
        )

        items = [
            CostItem(
                id="CAP-01",
                name="Pipeline construction",
                category="pipeline",
                subcategory="construction",
                stage="permitting_construction",
                classification=CostClassification.CAPITAL,
                depreciation_category=DepreciationCategory.PIPELINE,
                amount_base_year=1_000_000.0,
                base_year=2008,
                begin_year=3,
                end_year=3,
                quantity=1.0,
            ),
            CostItem(
                id="CAP-02",
                name="Platform construction",
                category="platform",
                subcategory="jacket",
                stage="permitting_construction",
                classification=CostClassification.CAPITAL,
                depreciation_category=DepreciationCategory.PLATFORM,
                amount_base_year=500_000.0,
                base_year=2008,
                begin_year=3,
                end_year=3,
                quantity=1.0,
            ),
            CostItem(
                id="EXP-01",
                name="Pipeline O&M",
                category="pipeline",
                subcategory="maintenance",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=50_000.0,
                base_year=2008,
                begin_year=4,
                end_year=33,
                recurrence="annual",
                quantity=1.0,
            ),
            CostItem(
                id="EXP-02",
                name="Monitoring",
                category="monitoring",
                subcategory="seismic",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=100_000.0,
                base_year=2008,
                begin_year=4,
                end_year=33,
                recurrence="annual",
                quantity=1.0,
            ),
        ]
        return CostCatalog(items=items, base_year=2008, currency="USD")

    def test_total_capital_sums_only_capital(self):
        catalog = self._make_catalog()
        assert catalog.total_capital() == 1_500_000.0  # 1M + 500K

    def test_total_expense_sums_only_expense(self):
        catalog = self._make_catalog()
        # Lifetime totals: (50K + 100K) * 30 years (year 4-33)
        assert catalog.total_expense() == 150_000.0 * 30  # $4,500,000

    def test_annual_schedule_returns_dataframe_with_correct_rows(self):
        catalog = self._make_catalog()
        df = catalog.annual_schedule(85)
        assert len(df) == 85
        assert "year" in df.columns

    def test_by_category_returns_dict(self):
        catalog = self._make_catalog()
        by_cat = catalog.by_category()
        assert "pipeline" in by_cat
        assert "platform" in by_cat
        assert "monitoring" in by_cat


# ============================================================================
# Pipeline hydraulic sizing tests
# ============================================================================


class TestReynoldsNumber:
    """Test Reynolds number matching VBA Reyn_N."""

    def test_reynolds_number_formula(self):
        """Re = 4 * qm / (pi * mu * D)"""
        from ccs_costs.costs.pipeline import reynolds_number

        # Typical CO2 pipeline values
        qm = 126.80  # kg/s (4 Mt/yr)
        mu = 5.0e-5  # Pa-s (typical supercritical CO2)
        D = 0.3  # m (approx 12 inch)

        Re = reynolds_number(qm, mu, D)
        expected = 4 * qm / (math.pi * mu * D)
        assert abs(Re - expected) / expected < 1e-10


class TestColebrookWhite:
    """Test Colebrook-White Fanning friction factor matching VBA FFF_Cole."""

    def test_convergence_within_1000_iterations(self):
        """Colebrook-White must converge for physically realistic Re and D."""
        from ccs_costs.costs.pipeline import colebrook_white_fanning

        # Turbulent flow in 12-inch pipe
        Re = 1e7
        D = 0.3048  # 12 inches in meters
        eta = 4.6e-5  # roughness (m)

        ff = colebrook_white_fanning(Re, D, eta)
        assert ff > 0
        assert ff < 0.1  # Fanning friction factor is always < 0.1 for turbulent

    def test_smooth_pipe_limit(self):
        """For very small roughness, friction factor approaches smooth-pipe value."""
        from ccs_costs.costs.pipeline import colebrook_white_fanning

        Re = 1e6
        D = 0.5
        eta = 1e-10  # nearly smooth

        ff = colebrook_white_fanning(Re, D, eta)
        assert ff > 0
        # Smooth-pipe Fanning ff for Re=1e6 is about 0.0029
        assert 0.001 < ff < 0.01


class TestStandardPipeSize:
    """Test standard pipe size mapping matching VBA Pipe_Size."""

    def test_maps_below_4_inches_to_4(self):
        from ccs_costs.costs.pipeline import standard_pipe_size

        # 3 inches -> 4 inch nominal
        result = standard_pipe_size(3.0 * 0.0254)  # convert to meters
        assert result == 4

    def test_maps_10_1_inches_to_12(self):
        from ccs_costs.costs.pipeline import standard_pipe_size

        result = standard_pipe_size(10.1 * 0.0254)
        assert result == 12

    def test_maps_8_5_inches_to_10(self):
        from ccs_costs.costs.pipeline import standard_pipe_size

        result = standard_pipe_size(8.5 * 0.0254)
        assert result == 10

    def test_maps_5_5_inches_to_6(self):
        from ccs_costs.costs.pipeline import standard_pipe_size

        result = standard_pipe_size(5.5 * 0.0254)
        assert result == 6

    def test_maps_15_inches_to_16(self):
        from ccs_costs.costs.pipeline import standard_pipe_size

        result = standard_pipe_size(15.0 * 0.0254)
        assert result == 16


class TestPipelineDiameter:
    """Test pipeline_diameter for NETL default scenario.

    NETL default formation (Formation 1, Chandeleur Area) pipeline parameters:
    From Surf Eq Cost sheet:
    - Pipeline length: 41.56 mi (D21)
    - Flow rate: 4 Mt/yr (D27)
    - Onshore pump outlet pressure (p_in): 2200 psig (Key_Inputs N62)
    - Min target pressure at storage (p_out): 1200 psig (Key_Inputs N57)
    - Mudline temperature: 55 F = 12.78 C = 285.93 K (D32)
    - CO2 density at pipeline conditions: 914.34 kg/m3 (D36, at 1700 psig, 55F)
    - CO2 viscosity at pipeline conditions: 9.53e-5 Pa-s (D37)
    - Roughness: 0.00015 ft = 4.572e-5 m (D25, McCollum & Ogden 2006)
    - Method: incompressible (Meth=1)
    - Friction method: Colebrook-White (fanfr_meth=3)

    Expected result: min diameter ~11.2 inches -> 12-inch nominal pipe size.
    """

    def test_netl_default_returns_12_inches(self):
        from ccs_costs.costs.pipeline import pipeline_diameter

        # NETL default parameters from Surf Eq Cost sheet
        length_km = 41.563589354870004 * 1.609344  # mi -> km
        flow_rate_tpa = 4_000_000.0  # 4 Mt/yr
        # Pressures from Key_Inputs: onshore pump outlet 2200 psig, target at site 1200 psig
        inlet_pressure_mpa = (2200 + 14.696) * 6894.757 / 1e6
        outlet_pressure_mpa = (1200 + 14.696) * 6894.757 / 1e6
        # Mudline temperature: 55 F = 12.78 C
        temperature_c = (55.0 - 32.0) * 5.0 / 9.0  # 12.78 C
        # CO2 at pipeline conditions (1700 psig, 55 F) from Surf Eq Cost
        co2_density = 914.344787659076  # kg/m3
        co2_viscosity = 9.531218413654335e-5  # Pa-s
        # Roughness from McCollum & Ogden: 0.00015 ft -> m
        roughness_m = 0.00015 * 0.3048  # 4.572e-5 m

        result = pipeline_diameter(
            flow_rate_tpa=flow_rate_tpa,
            length_km=length_km,
            inlet_pressure_mpa=inlet_pressure_mpa,
            outlet_pressure_mpa=outlet_pressure_mpa,
            temperature_c=temperature_c,
            co2_density_kgm3=co2_density,
            co2_viscosity_pas=co2_viscosity,
            roughness_m=roughness_m,
            elevation_change_m=0.0,
        )

        assert result["nominal_diameter_inches"] == 12
        # Minimum diameter should be between 10 and 12 inches
        assert 10.0 < result["min_diameter_inches"] < 12.0

    def test_returns_dict_with_expected_keys(self):
        from ccs_costs.costs.pipeline import pipeline_diameter

        result = pipeline_diameter(
            flow_rate_tpa=4_000_000.0,
            length_km=66.9,
            inlet_pressure_mpa=15.27,
            outlet_pressure_mpa=8.38,
            temperature_c=12.78,
            co2_density_kgm3=914.3,
            co2_viscosity_pas=9.5e-5,
            roughness_m=4.6e-5,
        )

        assert "min_diameter_m" in result
        assert "nominal_diameter_inches" in result
        assert result["min_diameter_m"] > 0


# ============================================================================
# Pipeline cost model tests
# ============================================================================


class TestNetlQuestorPipelineCosts:
    """Test NETL/QUE$TOR pipeline cost model.

    Reference values calibrated to NETL CO2_S_COM_Offshore v1.1 Cost Breakdown 1 (2008$):
    - Pipeline construction (12", 37.785 mi): CAPEX = $192,166,746 (2008$)
    - Pipeline O&M annual (12", 37.785 mi): $1,719,727 (2008$/yr)
    - Pipeline decommissioning: $1,593,000/mi (2008$, BSEE)
    - Total decom cost: $66,210,798 (2008$, D74)

    The Cost Breakdown 1 "Offshore Pipeline" row shows:
    - col3 (Capital, 2008$): $206,369,911
    - col4 (O&M total, 2008$): $127,445,903
    - col5 (Total, 2008$): $333,815,814

    NOTE: The $206M capital includes more than just pipeline construction --
    it also includes pump capital, building, road, custody transfer, header,
    control system, and pipeline decom. Similarly, O&M includes ROW lease,
    pump O&M/elec, building, road, header, and control system O&M.
    """

    def test_netl_pipeline_capex_for_12_inch(self):
        """NETL pipeline CAPEX formula: 3,762,510 * L_mi + 50,000,000 for 12-inch (2008$)."""
        from ccs_costs.costs.pipeline import pipeline_capex, PipelineCostModel

        # NETL uses distance from shore (37.785 mi), not total pipeline length
        dist_shore_mi = 37.7850812317
        length_km = dist_shore_mi * 1.609344
        diameter_m = 12.0 * 0.0254  # 12 inches in m

        capex = pipeline_capex(
            diameter_m=diameter_m,
            length_km=length_km,
            offshore=True,
            model=PipelineCostModel.NETL_QUESTOR,
        )

        # Expected: 3,762,510 * 37.785 + 50,000,000 = ~192,166,746 (2008$)
        # Calibrated to NETL CO2_S_COM_Offshore v1.1 Cost Breakdown 1
        expected_2008 = 3_762_510 * dist_shore_mi + 50_000_000
        assert abs(capex - expected_2008) / expected_2008 < 0.001  # 0.1%

    def test_netl_pipeline_om_for_12_inch(self):
        """NETL pipeline O&M formula: 34,065 * L_mi + 432,578 for 12-inch (2008$)."""
        from ccs_costs.costs.pipeline import pipeline_opex_annual, PipelineCostModel

        dist_shore_mi = 37.7850812317
        length_km = dist_shore_mi * 1.609344
        diameter_m = 12.0 * 0.0254

        opex = pipeline_opex_annual(
            diameter_m=diameter_m,
            length_km=length_km,
            model=PipelineCostModel.NETL_QUESTOR,
        )

        # Expected: 34,065 * 37.785 + 432,578 = ~1,719,727 (2008$/yr)
        # Calibrated to NETL CO2_S_COM_Offshore v1.1
        expected_2008 = 34_065 * dist_shore_mi + 432_578
        assert abs(opex - expected_2008) / expected_2008 < 0.001  # 0.1%

    def test_pipeline_decom_rate(self):
        """Pipeline decommissioning rate: $1,593,000/mile (2008$, BSEE)."""
        from ccs_costs.costs.pipeline import pipeline_decommissioning

        length_km = 41.563589354870004 * 1.609344  # full pipeline length
        decom = pipeline_decommissioning(length_km, offshore=True)

        # $1,593,000/mi * 41.56 mi = $66,210,798
        expected = 1_593_000.0 * 41.563589354870004
        assert abs(decom - expected) / expected < 0.001

    def test_netl_pipeline_total_matches_reference(self):
        """Verify pipeline-only total approximates NETL reference.

        The NETL Cost Breakdown total of $333.8M includes additional items
        beyond pipeline construction, O&M, and decom. The pipeline-only
        components should be a major fraction of that total.
        """
        from ccs_costs.costs.pipeline import (
            pipeline_capex,
            pipeline_opex_annual,
            pipeline_decommissioning,
            PipelineCostModel,
        )

        dist_shore_mi = 37.7850812317
        length_km = dist_shore_mi * 1.609344
        diameter_m = 12.0 * 0.0254
        full_length_km = 41.563589354870004 * 1.609344

        capex_2022 = pipeline_capex(diameter_m, length_km, True, PipelineCostModel.NETL_QUESTOR)
        om_annual_2022 = pipeline_opex_annual(diameter_m, length_km, PipelineCostModel.NETL_QUESTOR)
        decom_2008 = pipeline_decommissioning(full_length_km, True)

        # Verify each component is reasonable
        assert 150_000_000 < capex_2022 < 200_000_000  # ~163M 2022$
        assert 1_000_000 < om_annual_2022 < 3_000_000  # ~1.68M 2022$/yr
        assert 60_000_000 < decom_2008 < 70_000_000  # ~66M 2008$

    def test_calculate_pipeline_costs_returns_cost_items(self):
        """calculate_pipeline_costs returns PipelineCosts with CostItem list."""
        from ccs_costs.costs.pipeline import (
            calculate_pipeline_costs,
            pipeline_diameter,
            PipelineCostModel,
        )

        dia_result = pipeline_diameter(
            flow_rate_tpa=4_000_000.0,
            length_km=66.9,
            inlet_pressure_mpa=15.27,
            outlet_pressure_mpa=8.38,
            temperature_c=12.78,
            co2_density_kgm3=914.3,
            co2_viscosity_pas=9.5e-5,
        )

        costs = calculate_pipeline_costs(
            diameter_result=dia_result,
            length_km=66.9,
            model=PipelineCostModel.NETL_QUESTOR,
            offshore=True,
        )

        assert len(costs.items) >= 3  # CAPEX, O&M ops, O&M PISC, decom
        assert costs.capex > 0
        assert costs.opex_annual > 0
        assert costs.decommissioning > 0


class TestKnoope2014PipelineCosts:
    """Test Knoope 2014 pipeline cost model.

    Reference: Knoope et al. (2014), IJGGC 22, 25-46.
    Calibration: Northern Lights pipeline ~NOK 5M/km for 12-16" offshore.
    EUR/NOK approx 10.4 (2024).

    The Knoope model: CAPEX = a * D^b * L (EUR/km * km = EUR)
    with an offshore multiplier for subsea installation.
    """

    def test_knoope_12_inch_100km_offshore(self):
        """Knoope cost for 12-inch, 100km offshore should be in reasonable range.

        Northern Lights benchmark: ~NOK 500M for 100km = ~EUR 48M
        (~EUR 480K/km, derived from NOK 5M/km at ~10.4 NOK/EUR).

        Knoope typically gives higher costs than NL (competitive bid, benign route).
        Expect EUR 40M-200M range for 12", 100km offshore.
        """
        from ccs_costs.costs.pipeline import pipeline_capex, PipelineCostModel

        diameter_m = 12.0 * 0.0254  # 12 inches
        length_km = 100.0

        capex_eur = pipeline_capex(
            diameter_m=diameter_m,
            length_km=length_km,
            offshore=True,
            model=PipelineCostModel.KNOOPE_2014,
        )

        # Expect EUR 40M-200M for 100km offshore, 12"
        assert 40_000_000 < capex_eur < 200_000_000

    def test_knoope_cost_increases_with_diameter(self):
        """Larger diameter should cost more."""
        from ccs_costs.costs.pipeline import pipeline_capex, PipelineCostModel

        length_km = 100.0
        capex_12 = pipeline_capex(12 * 0.0254, length_km, True, PipelineCostModel.KNOOPE_2014)
        capex_20 = pipeline_capex(20 * 0.0254, length_km, True, PipelineCostModel.KNOOPE_2014)

        assert capex_20 > capex_12

    def test_knoope_offshore_more_expensive_than_onshore(self):
        """Offshore pipeline should cost more than onshore."""
        from ccs_costs.costs.pipeline import pipeline_capex, PipelineCostModel

        diameter_m = 12 * 0.0254
        length_km = 100.0

        capex_onshore = pipeline_capex(diameter_m, length_km, False, PipelineCostModel.KNOOPE_2014)
        capex_offshore = pipeline_capex(diameter_m, length_km, True, PipelineCostModel.KNOOPE_2014)

        assert capex_offshore > capex_onshore
