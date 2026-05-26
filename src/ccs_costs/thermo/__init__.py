"""Thermodynamic property modules for CO2 and brine.

Public API:
    CO2: co2_density, co2_viscosity, co2_compressibility
    Brine: brine_density, brine_viscosity
    Multiflash: get_co2_density, multiflash_available
    Models: CO2Properties, BrineProperties
"""

from pydantic import BaseModel

from ccs_costs.thermo.co2 import co2_density, co2_viscosity, co2_compressibility
from ccs_costs.thermo.brine import brine_density, brine_viscosity
from ccs_costs.thermo.multiflash import get_co2_density, multiflash_available

__all__ = [
    "co2_density",
    "co2_viscosity",
    "co2_compressibility",
    "brine_density",
    "brine_viscosity",
    "get_co2_density",
    "multiflash_available",
    "CO2Properties",
    "BrineProperties",
]


class CO2Properties(BaseModel):
    """CO2 thermophysical properties at given conditions."""

    pressure_mpa: float
    temperature_c: float
    density_kgm3: float
    viscosity_pas: float
    compressibility_z: float
    method: str  # "duan", "peng-robinson", or "multiflash"


class BrineProperties(BaseModel):
    """Brine thermophysical properties at given conditions."""

    pressure_mpa: float
    temperature_c: float
    salinity_ppm: float
    density_kgm3: float
    viscosity_pas: float
