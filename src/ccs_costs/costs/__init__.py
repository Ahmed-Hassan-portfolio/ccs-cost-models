"""Cost calculation modules for CCS projects.

This package provides cost estimation for all major CCS project components:
- catalog: Shared cost data models (CostItem, CostCatalog)
- pipeline: Pipeline hydraulic sizing and cost estimation
- drilling: Well cost regressions (NETL/QUE$TOR + IEAGHG 2005/2)
- platform: Platform jacket + subsea tieback infrastructure costs
- monitoring: MVA cost framework with schedule-driven calculations
- decommissioning: End-of-life well P&A, pipeline, platform removal
- regulatory: Region-specific permits, fees, and compliance costs
"""

from ccs_costs.costs.catalog import (
    CostCatalog,
    CostClassification,
    CostItem,
    DepreciationCategory,
    assemble_cost_catalog,
)
from ccs_costs.costs.monitoring import (
    MonitoringCosts,
    MonitoringPlan,
    MonitoringUnitCosts,
    calculate_monitoring_costs,
    load_monitoring_config,
)
from ccs_costs.costs.decommissioning import (
    DecommissioningCosts,
    calculate_decommissioning_costs,
)
from ccs_costs.costs.regulatory import (
    RegulatoryCosts,
    RegulatoryItem,
    calculate_regulatory_costs,
    load_regulatory_config,
)
from ccs_costs.costs.drilling import (
    DrillingCosts,
    DrillingRegression,
    IEAGHGDrillingRegression,
    NETLDrillingRegression,
    calculate_drilling_costs,
)
from ccs_costs.costs.pipeline import (
    PipelineCostModel,
    PipelineCosts,
    calculate_pipeline_costs,
    pipeline_capex,
    pipeline_decommissioning,
    pipeline_diameter,
    pipeline_opex_annual,
)
from ccs_costs.costs.platform import (
    InfrastructureModel,
    PlatformCosts,
    calculate_infrastructure_costs,
    platform_cost_jacket,
    subsea_tieback_cost,
)

__all__ = [
    "CostCatalog",
    "CostClassification",
    "CostItem",
    "DepreciationCategory",
    "assemble_cost_catalog",
    "DrillingCosts",
    "DrillingRegression",
    "IEAGHGDrillingRegression",
    "NETLDrillingRegression",
    "calculate_drilling_costs",
    "MonitoringCosts",
    "MonitoringPlan",
    "MonitoringUnitCosts",
    "calculate_monitoring_costs",
    "load_monitoring_config",
    "DecommissioningCosts",
    "calculate_decommissioning_costs",
    "RegulatoryCosts",
    "RegulatoryItem",
    "calculate_regulatory_costs",
    "load_regulatory_config",
    "InfrastructureModel",
    "PipelineCostModel",
    "PipelineCosts",
    "PlatformCosts",
    "calculate_infrastructure_costs",
    "calculate_pipeline_costs",
    "pipeline_capex",
    "pipeline_decommissioning",
    "pipeline_diameter",
    "pipeline_opex_annual",
    "platform_cost_jacket",
    "subsea_tieback_cost",
]
