"""Tests for storage coefficient lookup table.

Validates:
    - IEA GHG 2009/12 storage efficiency factors
    - NETL default formation coefficient = 0.0593 (P50)
    - Case-insensitive lookup
    - User-specified method bypass
    - Error handling with helpful messages
    - All 129 entries loadable with valid p10 < p50 < p90
    - Carbonate maps to same values as limestone
"""

import pytest

from ccs_costs.geo.storage import (
    StorageCoefficientMethod,
    get_coefficient_for_formation,
    storage_coefficient,
)
from ccs_costs.geo.formations import FormationProperties


class TestNETLDefaultFormation:
    """Test storage coefficient for NETL default formation (clastic/shallow shelf/reg_dip)."""

    def test_p50_exact(self):
        """P50 must be exactly 0.0593 for NETL default."""
        result = storage_coefficient("clastic", "shallow shelf", "reg_dip", "P50")
        assert result == 0.0593

    def test_p10(self):
        """P10 for default formation."""
        result = storage_coefficient("clastic", "shallow shelf", "reg_dip", "P10")
        assert result == pytest.approx(0.0506, abs=0.001)

    def test_p90(self):
        """P90 for default formation."""
        result = storage_coefficient("clastic", "shallow shelf", "reg_dip", "P90")
        assert result == 0.0677


class TestVariousLookups:
    """Test various lithology/environment/structure combinations."""

    def test_clastic_delta_dome(self):
        result = storage_coefficient("clastic", "delta", "dome", "P50")
        assert result == 0.1551

    def test_dolomite_general_general(self):
        result = storage_coefficient("dolomite", "general", "general", "P50")
        assert result == 0.0791

    def test_limestone_reef_anticline(self):
        result = storage_coefficient("limestone", "reef", "anticline", "P50")
        assert result == 0.0698

    def test_clastic_eolian_dome(self):
        result = storage_coefficient("clastic", "eolian", "dome", "P50")
        assert result == 0.1719

    def test_clastic_fluvial_reg_dip_p10(self):
        result = storage_coefficient("clastic", "fluvial", "reg_dip", "P10")
        assert result == pytest.approx(0.0533, abs=0.001)

    def test_limestone_shallow_shelf_dome_p90(self):
        result = storage_coefficient("limestone", "shallow shelf", "dome", "P90")
        assert result == 0.1262


class TestCaseInsensitivity:
    """Test that lookup is case-insensitive."""

    def test_uppercase_lithology(self):
        result = storage_coefficient("CLASTIC", "shallow shelf", "reg_dip", "P50")
        assert result == 0.0593

    def test_mixed_case(self):
        result = storage_coefficient("Clastic", "Shallow Shelf", "Reg_Dip", "P50")
        assert result == 0.0593

    def test_all_uppercase(self):
        result = storage_coefficient("CLASTIC", "SHALLOW SHELF", "REG_DIP", "P50")
        assert result == 0.0593

    def test_probability_case(self):
        """Probability string should be case-insensitive."""
        result = storage_coefficient("clastic", "shallow shelf", "reg_dip", "p50")
        assert result == 0.0593


class TestUserSpecifiedMethod:
    """Test user-specified storage coefficient bypass."""

    def test_returns_user_value(self):
        result = storage_coefficient(
            "clastic", "shallow shelf", "reg_dip", "P50",
            method=StorageCoefficientMethod.USER,
            user_value=0.05,
        )
        assert result == 0.05

    def test_raises_without_user_value(self):
        with pytest.raises(ValueError, match="user_value"):
            storage_coefficient(
                "clastic", "shallow shelf", "reg_dip", "P50",
                method=StorageCoefficientMethod.USER,
                user_value=None,
            )


class TestErrorHandling:
    """Test error handling with helpful messages."""

    def test_invalid_lithology(self):
        with pytest.raises(ValueError, match="clastic"):
            storage_coefficient("granite", "shallow shelf", "reg_dip", "P50")

    def test_sandstone_alias_works(self):
        """sandstone is aliased to clastic -- should NOT raise."""
        result = storage_coefficient("sandstone", "shallow shelf", "reg_dip", "P50")
        expected = storage_coefficient("clastic", "shallow shelf", "reg_dip", "P50")
        assert result == expected

    def test_invalid_environment(self):
        with pytest.raises(ValueError):
            storage_coefficient("clastic", "deep ocean", "reg_dip", "P50")

    def test_invalid_structure(self):
        with pytest.raises(ValueError):
            storage_coefficient("clastic", "shallow shelf", "horst", "P50")


class TestAllEntries:
    """Test that all 129 entries are loadable and have valid ordering."""

    def test_all_129_entries_valid(self):
        """Load the raw data and check all entries have p10 <= p50 <= p90."""
        import json
        from pathlib import Path

        data_path = Path(__file__).parent.parent.parent / "data" / "reference" / "storage_coefficients.json"
        with open(data_path) as f:
            data = json.load(f)

        entries = data["coefficients"]
        assert len(entries) == 129

        for entry in entries:
            p10 = entry["p10"]
            p50 = entry["p50"]
            p90 = entry["p90"]
            key = entry["lookup_key"]
            assert p10 <= p50, f"{key}: p10={p10} > p50={p50}"
            assert p50 <= p90, f"{key}: p50={p50} > p90={p90}"
            assert p10 > 0, f"{key}: p10={p10} <= 0"
            assert p90 < 1, f"{key}: p90={p90} >= 1"

    def test_all_entries_accessible_via_lookup(self):
        """Every entry in the table can be looked up via storage_coefficient."""
        import json
        from pathlib import Path

        data_path = Path(__file__).parent.parent.parent / "data" / "reference" / "storage_coefficients.json"
        with open(data_path) as f:
            data = json.load(f)

        for entry in data["coefficients"]:
            lith = entry["lithology"]
            dep_env = entry["depositional_environment"]
            struct = entry["structure"]
            # Should not raise
            result = storage_coefficient(lith, dep_env, struct, "P50")
            assert result == entry["p50"]


class TestCarbonateEquivalence:
    """Test that carbonate maps to same values as limestone for same environment/structure."""

    def test_carbonate_peritidal_general(self):
        carb = storage_coefficient("carbonate", "peritidal", "general", "P50")
        lime = storage_coefficient("limestone", "peritidal", "general", "P50")
        assert carb == lime

    def test_carbonate_reef_anticline(self):
        carb = storage_coefficient("carbonate", "reef", "anticline", "P50")
        lime = storage_coefficient("limestone", "reef", "anticline", "P50")
        assert carb == lime

    def test_carbonate_shallow_shelf_dome_p90(self):
        carb = storage_coefficient("carbonate", "shallow shelf", "dome", "P90")
        lime = storage_coefficient("limestone", "shallow shelf", "dome", "P90")
        assert carb == lime


class TestGetCoefficientForFormation:
    """Test convenience function that extracts from FormationProperties."""

    def test_formation_1_default(self):
        """Formation 1 (clastic/shallow shelf/regional_dip) should give 0.0593."""
        f1 = FormationProperties(
            id="1241_1",
            name="PL_A1",
            depth_m=1048.26,
            thickness_m=23.83,
            porosity=0.3225,
            permeability_md=533.4,
            temperature_c=47.86,
            pressure_mpa=11.19,
            lithology="clastic",
            depositional_environment="shallow shelf",
            structure_type="regional_dip",
        )
        result = get_coefficient_for_formation(f1, "P50")
        assert result == 0.0593
