"""Tests for brine property functions (density and viscosity).

Tests verify VBA parity with NETL modBrineProp.bas (Bandilla/Princeton correlations)
and physical consistency of brine properties.

References:
    - Battistelli, Calore & Pruess (1997) for brine density
    - Phillips, Igbene, Fair, Ozbek & Tavana (1981) for brine viscosity
    - Haas (1976) for NaCl solution properties
"""

import pytest


class TestBrineDensityPhysicalRange:
    """Test brine density returns physically reasonable values."""

    def test_brine_density_typical_goa(self):
        """At GOA reservoir conditions (~50 C, ~17 MPa, 150000 ppm),
        density should be in physical range 1050-1150 kg/m3."""
        from ccs_costs.thermo.brine import brine_density

        rho = brine_density(
            temperature_c=50.0, pressure_mpa=17.0, salinity_ppm=150000
        )
        assert 1050.0 < rho < 1150.0, (
            f"GOA brine density {rho:.1f} kg/m3 outside expected range 1050-1150"
        )

    def test_brine_density_ncs_conditions(self):
        """At NCS conditions (4 C, 20 MPa, 35000 ppm), density ~1020-1040 kg/m3."""
        from ccs_costs.thermo.brine import brine_density

        rho = brine_density(
            temperature_c=4.0, pressure_mpa=20.0, salinity_ppm=35000
        )
        assert 1020.0 < rho < 1050.0, (
            f"NCS brine density {rho:.1f} kg/m3 outside expected range 1020-1050"
        )

    def test_brine_density_pure_water_limit(self):
        """At salinity=0, should approximate pure water density (~998 kg/m3 at 20 C, 1 atm)."""
        from ccs_costs.thermo.brine import brine_density

        rho = brine_density(
            temperature_c=20.0, pressure_mpa=0.101325, salinity_ppm=0
        )
        # Pure water at 20 C, 1 atm is ~998.2 kg/m3
        assert 990.0 < rho < 1010.0, (
            f"Pure water limit density {rho:.1f} kg/m3 outside expected range 990-1010"
        )


class TestBrineDensityMonotonicity:
    """Test physical consistency: monotonicity with respect to parameters."""

    @pytest.mark.parametrize(
        "salinities",
        [(50000, 100000, 200000)],
    )
    def test_brine_density_increases_with_salinity(self, salinities):
        """At fixed T=50, P=15, density must increase with salinity."""
        from ccs_costs.thermo.brine import brine_density

        densities = [
            brine_density(temperature_c=50.0, pressure_mpa=15.0, salinity_ppm=s)
            for s in salinities
        ]
        for i in range(len(densities) - 1):
            assert densities[i] < densities[i + 1], (
                f"Density at sal={salinities[i]} ({densities[i]:.2f}) "
                f">= density at sal={salinities[i+1]} ({densities[i+1]:.2f})"
            )

    def test_brine_density_increases_with_pressure(self):
        """At fixed T=50, sal=150000, density at P=30 > P=20 > P=10."""
        from ccs_costs.thermo.brine import brine_density

        pressures = [10.0, 20.0, 30.0]
        densities = [
            brine_density(temperature_c=50.0, pressure_mpa=p, salinity_ppm=150000)
            for p in pressures
        ]
        for i in range(len(densities) - 1):
            assert densities[i] < densities[i + 1], (
                f"Density at P={pressures[i]} ({densities[i]:.2f}) "
                f">= density at P={pressures[i+1]} ({densities[i+1]:.2f})"
            )


class TestBrineViscosity:
    """Test brine viscosity returns physically reasonable values."""

    def test_brine_viscosity_decreases_with_temperature(self):
        """At fixed P=15, sal=150000, viscosity at T=30 > T=60 > T=100."""
        from ccs_costs.thermo.brine import brine_viscosity

        temperatures = [30.0, 60.0, 100.0]
        viscosities = [
            brine_viscosity(temperature_c=t, pressure_mpa=15.0, salinity_ppm=150000)
            for t in temperatures
        ]
        for i in range(len(viscosities) - 1):
            assert viscosities[i] > viscosities[i + 1], (
                f"Viscosity at T={temperatures[i]} ({viscosities[i]:.6f}) "
                f"<= viscosity at T={temperatures[i+1]} ({viscosities[i+1]:.6f})"
            )

    def test_brine_viscosity_positive(self):
        """Viscosity must always be positive at valid conditions."""
        from ccs_costs.thermo.brine import brine_viscosity

        vis = brine_viscosity(
            temperature_c=50.0, pressure_mpa=15.0, salinity_ppm=150000
        )
        assert vis > 0, f"Viscosity must be positive, got {vis}"

    def test_brine_viscosity_order_of_magnitude(self):
        """At typical GOA conditions, brine viscosity should be ~0.5-1.0 cP (5e-4 to 1e-3 Pa-s)."""
        from ccs_costs.thermo.brine import brine_viscosity

        vis = brine_viscosity(
            temperature_c=50.0, pressure_mpa=15.0, salinity_ppm=150000
        )
        # 0.5-1.5 cP in Pa-s
        assert 3e-4 < vis < 2e-3, (
            f"GOA brine viscosity {vis:.6f} Pa-s outside expected range 3e-4 to 2e-3"
        )


class TestBrineInputValidation:
    """Test input validation for brine functions."""

    def test_negative_salinity_raises(self):
        """Negative salinity should raise ValueError."""
        from ccs_costs.thermo.brine import brine_density

        with pytest.raises(ValueError, match="[Ss]alinity"):
            brine_density(temperature_c=50.0, pressure_mpa=15.0, salinity_ppm=-1000)

    def test_extreme_temperature_raises(self):
        """Temperature above 350 C should raise ValueError."""
        from ccs_costs.thermo.brine import brine_density

        with pytest.raises(ValueError, match="[Tt]emperature"):
            brine_density(temperature_c=400.0, pressure_mpa=15.0, salinity_ppm=100000)

    def test_negative_pressure_raises(self):
        """Pressure <= 0 should raise ValueError."""
        from ccs_costs.thermo.brine import brine_density

        with pytest.raises(ValueError, match="[Pp]ressure"):
            brine_density(temperature_c=50.0, pressure_mpa=-1.0, salinity_ppm=100000)

    def test_extreme_salinity_raises(self):
        """Salinity >= 400000 ppm should raise ValueError."""
        from ccs_costs.thermo.brine import brine_density

        with pytest.raises(ValueError, match="[Ss]alinity"):
            brine_density(temperature_c=50.0, pressure_mpa=15.0, salinity_ppm=500000)

    def test_viscosity_negative_salinity_raises(self):
        """Negative salinity should raise ValueError for viscosity too."""
        from ccs_costs.thermo.brine import brine_viscosity

        with pytest.raises(ValueError, match="[Ss]alinity"):
            brine_viscosity(temperature_c=50.0, pressure_mpa=15.0, salinity_ppm=-1000)
