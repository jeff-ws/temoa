#!/usr/bin/env python

"""
Tools for Energy Model Optimization and Analysis (Temoa): 
An open source framework for energy systems optimization modeling

Copyright (C) 2015,  NC State University

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

A complete copy of the GNU General Public License v2 (GPLv2) is available 
in LICENSE.txt.  Users uncompressing this from an archive may not have 
received this license file.  If not, see <http://www.gnu.org/licenses/>.
"""
import logging
import os
from datetime import datetime
from itertools import product

from pyomo.environ import AbstractModel, Set, Param, BuildAction, Var, NonNegativeReals, Objective, minimize

from definitions import PROJECT_ROOT
from src.temoa_model.temoa_initialize import *
from src.temoa_model.temoa_rules import *

# set the target folder for output from this run
output_path = os.path.join(PROJECT_ROOT, "output_files", datetime.now().strftime("%Y-%m-%d %H%Mh"))
if not os.path.exists(output_path):
    os.mkdir(output_path)

# set up logger
logger = logging.getLogger(__name__)
logging.getLogger("pyomo").setLevel(logging.INFO)
logging.getLogger("matplotlib").setLevel(logging.WARNING)
filename = "log.log"
logging.basicConfig(
    filename=os.path.join(output_path, filename),
    filemode="w",
    format="%(asctime)s | %(module)s | %(levelname)s | %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.DEBUG,  # <-- global change for project is here
)



class TemoaModel(AbstractModel):
    """
    An instance of a Temoa Model
    """

    """
    Organization:  ATT, there are model components in here (the latter part of the file) and "helper"
    constructs (dictionaries and sets) in the first part of the file

    temoa_rules.py is intended to host the rules used to construct constraints (only)
    temoa_initialize.py is intended to host the constructs to build out the "helper" constructs from raw data

    refactoring note:  All model components were brought into this 1 class from other modules so that:
    (1)  They are centralized within the class
    (2)  Any IDE can use introspection on the TemoaModel class for code-completion accuracy and error checking
         In this module or in the temoa_rules module
    (3)  Users can augment the model here and in the rules, as needed with code completion / type checking

    """
    def __init__(self, *args, **kwds):
        AbstractModel.__init__(self, *args, **kwds)

        # define the secondary data structures.  Most of these appear to be intermediate products from the
        # build and feed model components.
        self.processInputs = dict()
        self.processOutputs = dict()
        self.processLoans = dict()
        self.activeFlow_rpsditvo = None
        self.activeFlow_rpitvo = None
        self.activeFlex_rpsditvo = None
        self.activeFlex_rpitvo = None
        self.activeFlowInStorage_rpsditvo = None
        self.activeCurtailment_rpsditvo = None
        self.activeActivity_rptv = None
        self.activeCapacity_rtv = None
        self.activeCapacityAvailable_rpt = None
        self.activeCapacityAvailable_rptv = None
        self.commodityDStreamProcess = dict()  # The downstream process of a commodity during a period
        self.commodityUStreamProcess = dict()  # The upstream process of a commodity during a period
        self.ProcessInputsByOutput = dict()
        self.ProcessOutputsByInput = dict()
        self.processTechs = dict()
        self.processReservePeriods = dict()
        self.processVintages = dict()
        self.baseloadVintages = dict()
        self.curtailmentVintages = dict()
        self.storageVintages = dict()
        self.rampVintages = dict()
        self.inputsplitVintages = dict()
        self.inputsplitaverageVintages = dict()
        self.outputsplitVintages = dict()
        self.ProcessByPeriodAndOutput = dict()
        self.exportRegions = dict()
        self.importRegions = dict()
        self.flex_commodities = set()

        # ---------------------------------------------------------------
        # Define sets.
        # Sets are collections of items used to index parameters and variables
        # ---------------------------------------------------------------

        # Define time periods
        self.time_exist = Set(ordered=True)
        self.time_future = Set(ordered=True)
        self.time_optimize = Set(ordered=True, initialize=init_set_time_optimize)
        # Define time period vintages to track capacity installation
        self.vintage_exist = Set(ordered=True, initialize=init_set_vintage_exist)
        self.vintage_optimize = Set(ordered=True, initialize=init_set_vintage_optimize)
        self.vintage_all = self.time_exist | self.time_optimize
        # Perform some basic validation on the specified time periods.
        self.validate_time = BuildAction(rule=validate_time)

        # Define the model time slices
        self.time_season = Set(ordered=True)
        self.time_of_day = Set(ordered=True)

        # Define regions
        self.regions = Set()
        # RegionalIndices is the set of all the possible combinations of interregional
        # exhanges plus original region indices. If tech_exchange is empty, RegionalIndices =regions.
        self.RegionalIndices = Set(initialize=CreateRegionalIndices)

        # Define technology-related sets
        self.tech_resource = Set()
        self.tech_production = Set()
        self.tech_all = self.tech_resource | self.tech_production
        self.tech_baseload = Set(within=self.tech_all)
        self.tech_storage = Set(within=self.tech_all)
        self.tech_reserve = Set(within=self.tech_all)
        self.tech_ramping = Set(within=self.tech_all)
        self.tech_capacity_min = Set(within=self.tech_all)
        self.tech_capacity_max = Set(within=self.tech_all)
        self.tech_curtailment = Set(within=self.tech_all)
        self.tech_flex = Set(within=self.tech_all)
        self.tech_exchange = Set(within=self.tech_all)
        self.groups = Set(dimen=1)  # Define groups for technologies
        self.tech_groups = Set(within=self.tech_all)  # Define techs used in groups
        self.tech_annual = Set(within=self.tech_all)  # Define techs with constant output
        self.tech_variable = Set(
            within=self.tech_all)  # Define techs for use with TechInputSplitAverage constraint, where techs have variable annual output but the user wishes to constrain them annually

        # Define commodity-related sets
        self.commodity_demand = Set()
        self.commodity_emissions = Set()
        self.commodity_physical = Set()
        self.commodity_carrier = self.commodity_physical | self.commodity_demand
        self.commodity_all = self.commodity_carrier | self.commodity_emissions

        # Define sets for MGA weighting
        self.tech_mga = Set(within=self.tech_all)
        self.tech_electric = Set(within=self.tech_all)
        self.tech_transport = Set(within=self.tech_all)
        self.tech_industrial = Set(within=self.tech_all)
        self.tech_commercial = Set(within=self.tech_all)
        self.tech_residential = Set(within=self.tech_all)
        self.tech_PowerPlants = Set(within=self.tech_all)

        # ---------------------------------------------------------------
        # Define parameters.
        # In order to increase model efficiency, we use sparse
        # indexing of parameters, variables, and equations to prevent the
        # creation of indices for which no data exists. While basic model sets
        # are defined above, sparse index sets are defined below adjacent to the
        # appropriate parameter, variable, or constraint and all are initialized
        # in temoa_initialize.py.
        # Because the function calls that define the sparse index sets obscure the
        # sets utilized, we use a suffix that includes a one character name for each
        # set. Example: "_tv" indicates a set defined over "technology" and "vintage".
        # The complete index set is: psditvo, where p=period, s=season, d=day,
        # i=input commodity, t=technology, v=vintage, o=output commodity.
        # ---------------------------------------------------------------

        self.GlobalDiscountRate = Param()

        # Define time-related parameters
        self.PeriodLength = Param(self.time_optimize, initialize=ParamPeriodLength)
        self.SegFrac = Param(self.time_season, self.time_of_day)
        self.validate_SegFrac = BuildAction(rule=validate_SegFrac)

        # Define demand- and resource-related parameters
        self.DemandDefaultDistribution = Param(self.time_season, self.time_of_day, mutable=True)
        self.DemandSpecificDistribution = Param(
            self.regions, self.time_season, self.time_of_day, self.commodity_demand, mutable=True
        )

        self.Demand = Param(self.regions, self.time_optimize, self.commodity_demand)
        self.initialize_Demands = BuildAction(rule=CreateDemands)

        self.ResourceBound = Param(self.regions, self.time_optimize, self.commodity_physical)

        # Define technology performance parameters
        self.CapacityToActivity = Param(self.RegionalIndices, self.tech_all, default=1)

        self.ExistingCapacity = Param(self.RegionalIndices, self.tech_all, self.vintage_exist)

        self.Efficiency = Param(
            self.RegionalIndices, self.commodity_physical, self.tech_all, self.vintage_all, self.commodity_carrier
        )
        self.validate_UsedEfficiencyIndices = BuildAction(rule=CheckEfficiencyIndices)

        self.CapacityFactor_rsdtv = Set(dimen=5, initialize=CapacityFactorProcessIndices)
        self.CapacityFactorProcess = Param(self.CapacityFactor_rsdtv, mutable=True)

        self.CapacityFactor_rsdt = Set(dimen=4, initialize=CapacityFactorTechIndices)
        self.CapacityFactorTech = Param(self.CapacityFactor_rsdt, default=1)

        self.initialize_CapacityFactors = BuildAction(rule=CreateCapacityFactors)

        self.LifetimeTech = Param(self.RegionalIndices, self.tech_all, default=40)
        self.LifetimeLoanTech = Param(self.RegionalIndices, self.tech_all, default=10)

        self.LifetimeProcess_rtv = Set(dimen=3, initialize=LifetimeProcessIndices)
        self.LifetimeProcess = Param(self.LifetimeProcess_rtv, mutable=True)

        self.LifetimeLoanProcess_rtv = Set(dimen=3, initialize=LifetimeLoanProcessIndices)
        self.LifetimeLoanProcess = Param(self.LifetimeLoanProcess_rtv, mutable=True)
        self.initialize_Lifetimes = BuildAction(rule=CreateLifetimes)

        self.TechInputSplit = Param(self.regions, self.time_optimize, self.commodity_physical, self.tech_all)
        self.TechInputSplitAverage = Param(self.regions, self.time_optimize, self.commodity_physical, self.tech_variable)
        self.TechOutputSplit = Param(self.regions, self.time_optimize, self.tech_all, self.commodity_carrier)

        # The method below creates a series of helper functions that are used to
        # perform the sparse matrix of indexing for the parameters, variables, and
        # equations below.
        self.Create_SparseDicts = BuildAction(rule=CreateSparseDicts)

        # Define technology cost parameters
        self.CostFixed_rptv = Set(dimen=4, initialize=CostFixedIndices)
        self.CostFixed = Param(self.CostFixed_rptv, mutable=True)

        self.CostFixedVintageDefault_rtv = Set(
            dimen=3, initialize=lambda self: set((r, t, v) for r, p, t, v in self.CostFixed_rptv)
        )
        self.CostFixedVintageDefault = Param(self.CostFixedVintageDefault_rtv)

        self.CostInvest_rtv = Set(dimen=3, initialize=CostInvestIndices)
        self.CostInvest = Param(self.CostInvest_rtv)

        self.CostVariable_rptv = Set(dimen=4, initialize=CostVariableIndices)
        self.CostVariable = Param(self.CostVariable_rptv, mutable=True)

        self.CostVariableVintageDefault_rtv = Set(
            dimen=3, initialize=lambda self: set((r, t, v) for r, p, t, v in self.CostVariable_rptv)
        )
        self.CostVariableVintageDefault = Param(self.CostVariableVintageDefault_rtv)

        self.initialize_Costs = BuildAction(rule=CreateCosts)

        self.DiscountRate_rtv = Set(dimen=3, initialize=lambda self: self.CostInvest.keys())
        self.DiscountRate = Param(self.DiscountRate_rtv, default=0.05)

        self.Loan_rtv = Set(dimen=3, initialize=lambda self: self.CostInvest.keys())
        self.LoanAnnualize = Param(self.Loan_rtv, initialize=ParamLoanAnnualize_rule)

        self.ModelProcessLife_rptv = Set(dimen=4, initialize=ModelProcessLifeIndices)
        self.ModelProcessLife = Param(
            self.ModelProcessLife_rptv, initialize=ParamModelProcessLife_rule
        )

        self.ProcessLifeFrac_rptv = Set(dimen=4, initialize=ModelProcessLifeIndices)
        self.ProcessLifeFrac = Param(
            self.ProcessLifeFrac_rptv, initialize=ParamProcessLifeFraction_rule
        )

        # Define parameters associated with user-defined constraints
        self.RegionalGlobalIndices = Set(initialize=RegionalGlobalInitializedIndices)
        self.MinCapacity = Param(self.RegionalIndices, self.time_optimize, self.tech_all)
        self.MaxCapacity = Param(self.RegionalIndices, self.time_optimize, self.tech_all)
        self.MaxResource = Param(self.RegionalIndices, self.tech_all)
        self.MinCapacitySum = Param(self.time_optimize)  # for techs in tech_capacity
        self.MaxCapacitySum = Param(self.time_optimize)  # for techs in tech_capacity
        self.MaxActivity = Param(self.RegionalGlobalIndices, self.time_optimize, self.tech_all)
        self.MinActivity = Param(self.RegionalGlobalIndices, self.time_optimize, self.tech_all)
        self.GrowthRateMax = Param(self.RegionalIndices, self.tech_all)
        self.GrowthRateSeed = Param(self.RegionalIndices, self.tech_all)
        self.EmissionLimit = Param(self.RegionalGlobalIndices, self.time_optimize, self.commodity_emissions)
        self.EmissionActivity_reitvo = Set(dimen=6, initialize=EmissionActivityIndices)
        self.EmissionActivity = Param(self.EmissionActivity_reitvo)
        self.MinGenGroupWeight = Param(self.RegionalIndices, self.tech_groups, self.groups, default=0)
        self.MinGenGroupTarget = Param(self.time_optimize, self.groups)
        self.LinkedTechs = Param(self.RegionalIndices, self.tech_all, self.commodity_emissions)

        # Define parameters associated with electric sector operation
        self.RampUp = Param(self.regions, self.tech_ramping)
        self.RampDown = Param(self.regions, self.tech_ramping)
        self.CapacityCredit = Param(self.RegionalIndices, self.time_optimize, self.tech_all, self.vintage_all, default=1)
        self.PlanningReserveMargin = Param(self.regions, default=0.2)
        # Storage duration is expressed in hours
        self.StorageDuration = Param(self.regions, self.tech_storage, default=4)
        # Initial storage charge level, expressed as fraction of full energy capacity.
        # If the parameter is not defined, the model optimizes the initial storage charge level.
        self.StorageInit_rtv = Set(dimen=3, initialize=StorageInitIndices)
        self.StorageInitFrac = Param(self.StorageInit_rtv)

        self.MyopicBaseyear = Param(default=0, mutable=True)

        # ---------------------------------------------------------------
        # Define Decision Variables.
        # Decision variables are optimized in order to minimize cost.
        # Base decision variables represent the lowest-level variables
        # in the model. Derived decision variables are calculated for
        # convenience, where 1 or more indices in the base variables are
        # summed over.
        # ---------------------------------------------------------------
        # Define base decision variables
        self.FlowVar_rpsditvo = Set(dimen=8, initialize=FlowVariableIndices)
        self.V_FlowOut = Var(self.FlowVar_rpsditvo, domain=NonNegativeReals)
        self.FlowVarAnnual_rpitvo = Set(dimen=6, initialize=FlowVariableAnnualIndices)
        self.V_FlowOutAnnual = Var(self.FlowVarAnnual_rpitvo, domain=NonNegativeReals)

        self.FlexVar_rpsditvo = Set(dimen=8, initialize=FlexVariablelIndices)
        self.V_Flex = Var(self.FlexVar_rpsditvo, domain=NonNegativeReals)
        self.FlexVarAnnual_rpitvo = Set(dimen=6, initialize=FlexVariableAnnualIndices)
        self.V_FlexAnnual = Var(self.FlexVarAnnual_rpitvo, domain=NonNegativeReals)

        self.CurtailmentVar_rpsditvo = Set(dimen=8, initialize=CurtailmentVariableIndices)
        self.V_Curtailment = Var(self.CurtailmentVar_rpsditvo, domain=NonNegativeReals)

        self.FlowInStorage_rpsditvo = Set(dimen=8, initialize=FlowInStorageVariableIndices)
        self.V_FlowIn = Var(self.FlowInStorage_rpsditvo, domain=NonNegativeReals)
        self.StorageLevel_rpsdtv = Set(dimen=6, initialize=StorageVariableIndices)
        self.V_StorageLevel = Var(self.StorageLevel_rpsdtv, domain=NonNegativeReals)
        self.V_StorageInit = Var(self.StorageInit_rtv, domain=NonNegativeReals)

        # Derived decision variables

        self.CapacityVar_rtv = Set(dimen=3, initialize=CapacityVariableIndices)
        self.V_Capacity = Var(self.CapacityVar_rtv, domain=NonNegativeReals)

        self.CapacityAvailableVar_rpt = Set(
            dimen=3, initialize=CapacityAvailableVariableIndices
        )
        self.V_CapacityAvailableByPeriodAndTech = Var(
            self.CapacityAvailableVar_rpt, domain=NonNegativeReals
        )

        # ---------------------------------------------------------------
        # Declare the Objective Function.
        # ---------------------------------------------------------------
        self.TotalCost = Objective(rule=TotalCost_rule, sense=minimize)

        # ---------------------------------------------------------------
        # Declare the Constraints.
        # Constraints are specified to ensure proper system behavior,
        # and also to calculate some derived quantities. Note that descriptions
        # of these constraints are provided in the associated comment blocks
        # in temoa_rules.py, where the constraints are defined.
        # ---------------------------------------------------------------

        # Declare constraints to calculate derived decision variables

        self.CapacityConstraint_rpsdtv = Set(dimen=6, initialize=CapacityConstraintIndices)
        self.CapacityConstraint = Constraint(
            self.CapacityConstraint_rpsdtv, rule=Capacity_Constraint)

        self.CapacityAnnualConstraint_rptv = Set(dimen=4, initialize=CapacityAnnualConstraintIndices)
        self.CapacityAnnualConstraint = Constraint(
            self.CapacityAnnualConstraint_rptv, rule=CapacityAnnual_Constraint)

        self.CapacityAvailableByPeriodAndTechConstraint = Constraint(
            self.CapacityAvailableVar_rpt, rule=CapacityAvailableByPeriodAndTech_Constraint
        )

        self.ExistingCapacityConstraint_rtv = Set(
            dimen=3, initialize=lambda self: self.ExistingCapacity.sparse_iterkeys()
        )
        self.ExistingCapacityConstraint = Constraint(
            self.ExistingCapacityConstraint_rtv, rule=ExistingCapacity_Constraint
        )

        # Declare core model constraints that ensure proper system functioning
        # In driving order, starting with the need to meet end-use demands

        self.DemandConstraint_rpsdc = Set(dimen=5, initialize=DemandConstraintIndices)
        self.DemandConstraint = Constraint(self.DemandConstraint_rpsdc, rule=Demand_Constraint)

        self.DemandActivityConstraint_rpsdtv_dem_s0d0 = Set(
            dimen=9, initialize=DemandActivityConstraintIndices
        )
        self.DemandActivityConstraint = Constraint(
            self.DemandActivityConstraint_rpsdtv_dem_s0d0, rule=DemandActivity_Constraint
        )

        self.CommodityBalanceConstraint_rpsdc = Set(
            dimen=5, initialize=CommodityBalanceConstraintIndices
        )
        self.CommodityBalanceConstraint = Constraint(
            self.CommodityBalanceConstraint_rpsdc, rule=CommodityBalance_Constraint
        )

        self.CommodityBalanceAnnualConstraint_rpc = Set(
            dimen=3, initialize=CommodityBalanceAnnualConstraintIndices
        )
        self.CommodityBalanceAnnualConstraint = Constraint(
            self.CommodityBalanceAnnualConstraint_rpc, rule=CommodityBalanceAnnual_Constraint
        )

        self.ResourceConstraint_rpr = Set(
            dimen=3, initialize=lambda self: self.ResourceBound.sparse_iterkeys()
        )
        self.ResourceExtractionConstraint = Constraint(
            self.ResourceConstraint_rpr, rule=ResourceExtraction_Constraint
        )

        self.BaseloadDiurnalConstraint_rpsdtv = Set(
            dimen=6, initialize=BaseloadDiurnalConstraintIndices
        )
        self.BaseloadDiurnalConstraint = Constraint(
            self.BaseloadDiurnalConstraint_rpsdtv, rule=BaseloadDiurnal_Constraint
        )

        self.RegionalExchangeCapacityConstraint_rrtv = Set(
            dimen=4, initialize=RegionalExchangeCapacityConstraintIndices
        )
        self.RegionalExchangeCapacityConstraint = Constraint(
            self.RegionalExchangeCapacityConstraint_rrtv, rule=RegionalExchangeCapacity_Constraint)

        # This set works for all the storage-related constraints
        self.StorageConstraints_rpsdtv = Set(dimen=6, initialize=StorageVariableIndices)
        self.StorageEnergyConstraint = Constraint(
            self.StorageConstraints_rpsdtv, rule=StorageEnergy_Constraint
        )

        self.StorageEnergyUpperBoundConstraint = Constraint(
            self.StorageConstraints_rpsdtv, rule=StorageEnergyUpperBound_Constraint
        )

        self.StorageChargeRateConstraint = Constraint(
            self.StorageConstraints_rpsdtv, rule=StorageChargeRate_Constraint
        )

        self.StorageDischargeRateConstraint = Constraint(
            self.StorageConstraints_rpsdtv, rule=StorageDischargeRate_Constraint
        )

        self.StorageThroughputConstraint = Constraint(
            self.StorageConstraints_rpsdtv, rule=StorageThroughput_Constraint
        )

        self.StorageInitConstraint_rtv = Set(dimen=2, initialize=StorageInitConstraintIndices)
        self.StorageInitConstraint = Constraint(
            self.StorageInitConstraint_rtv, rule=StorageInit_Constraint
        )

        self.RampConstraintDay_rpsdtv = Set(dimen=6, initialize=RampConstraintDayIndices)
        self.RampUpConstraintDay = Constraint(
            self.RampConstraintDay_rpsdtv, rule=RampUpDay_Constraint
        )
        self.RampDownConstraintDay = Constraint(
            self.RampConstraintDay_rpsdtv, rule=RampDownDay_Constraint
        )

        self.RampConstraintSeason_rpstv = Set(dimen=5, initialize=RampConstraintSeasonIndices)
        self.RampUpConstraintSeason = Constraint(
            self.RampConstraintSeason_rpstv, rule=RampUpSeason_Constraint
        )
        self.RampDownConstraintSeason = Constraint(
            self.RampConstraintSeason_rpstv, rule=RampDownSeason_Constraint
        )

        self.RampConstraintPeriod_rptv = Set(dimen=4, initialize=RampConstraintPeriodIndices)
        self.RampUpConstraintPeriod = Constraint(
            self.RampConstraintPeriod_rptv, rule=RampUpPeriod_Constraint
        )
        self.RampDownConstraintPeriod = Constraint(
            self.RampConstraintPeriod_rptv, rule=RampDownPeriod_Constraint
        )

        self.ReserveMargin_rpsd = Set(dimen=4, initialize=ReserveMarginIndices)
        self.ReserveMarginConstraint = Constraint(
            self.ReserveMargin_rpsd, rule=ReserveMargin_Constraint
        )

        self.EmissionLimitConstraint_rpe = Set(
            dimen=3, initialize=lambda self: self.EmissionLimit.sparse_iterkeys()
        )
        self.EmissionLimitConstraint = Constraint(
            self.EmissionLimitConstraint_rpe, rule=EmissionLimit_Constraint
        )


        self.GrowthRateMaxConstraint_rtv = Set(
            dimen=3,
            initialize=lambda self: set(
                product(self.time_optimize, self.GrowthRateMax.sparse_iterkeys())
            ),
        )
        self.GrowthRateConstraint = Constraint(
            self.GrowthRateMaxConstraint_rtv, rule=GrowthRateConstraint_rule
        )

        self.MaxActivityConstraint_rpt = Set(
            dimen=3, initialize=lambda self: self.MaxActivity.sparse_iterkeys()
        )
        self.MaxActivityConstraint = Constraint(
            self.MaxActivityConstraint_rpt, rule=MaxActivity_Constraint
        )

        self.MinActivityConstraint_rpt = Set(
            dimen=3, initialize=lambda self: self.MinActivity.sparse_iterkeys()
        )
        self.MinActivityConstraint = Constraint(
            self.MinActivityConstraint_rpt, rule=MinActivity_Constraint
        )

        self.MinActivityGroup_pg = Set(
            dimen=2, initialize=lambda self: self.MinGenGroupTarget.sparse_iterkeys()
        )
        self.MinActivityGroup = Constraint(
            self.MinActivityGroup_pg, rule=MinActivityGroup_Constraint
        )

        self.MaxCapacityConstraint_rpt = Set(
            dimen=3, initialize=lambda self: self.MaxCapacity.sparse_iterkeys()
        )
        self.MaxCapacityConstraint = Constraint(
            self.MaxCapacityConstraint_rpt, rule=MaxCapacity_Constraint
        )

        self.MaxResourceConstraint_rt = Set(
            dimen=2, initialize=lambda self: self.MaxResource.sparse_iterkeys()
        )
        self.MaxResourceConstraint = Constraint(
            self.MaxResourceConstraint_rt, rule=MaxResource_Constraint
        )

        self.MaxCapacitySetConstraint_rp = Set(
            dimen=2, initialize=lambda self: self.MaxCapacitySum.sparse_iterkeys()
        )
        self.MaxCapacitySetConstraint = Constraint(
            self.MaxCapacitySetConstraint_rp, rule=MaxCapacitySet_Constraint
        )

        self.MinCapacityConstraint_rpt = Set(
            dimen=3, initialize=lambda self: self.MinCapacity.sparse_iterkeys()
        )
        self.MinCapacityConstraint = Constraint(
            self.MinCapacityConstraint_rpt, rule=MinCapacity_Constraint
        )

        self.MinCapacitySetConstraint_rp = Set(
            dimen=2, initialize=lambda self: self.MinCapacitySum.sparse_iterkeys()
        )
        self.MinCapacitySetConstraint = Constraint(
            self.MinCapacitySetConstraint_rp, rule=MinCapacitySet_Constraint
        )

        self.TechInputSplitConstraint_rpsditv = Set(
            dimen=7, initialize=TechInputSplitConstraintIndices
        )
        self.TechInputSplitConstraint = Constraint(
            self.TechInputSplitConstraint_rpsditv, rule=TechInputSplit_Constraint
        )

        self.TechInputSplitAnnualConstraint_rpitv = Set(
            dimen=5, initialize=TechInputSplitAnnualConstraintIndices
        )
        self.TechInputSplitAnnualConstraint = Constraint(
            self.TechInputSplitAnnualConstraint_rpitv, rule=TechInputSplitAnnual_Constraint
        )

        self.TechInputSplitAverageConstraint_rpitv = Set(
            dimen=5, initialize=TechInputSplitAverageConstraintIndices
        )
        self.TechInputSplitAverageConstraint = Constraint(
            self.TechInputSplitAverageConstraint_rpitv, rule=TechInputSplitAverage_Constraint
        )

        self.TechOutputSplitConstraint_rpsdtvo = Set(
            dimen=7, initialize=TechOutputSplitConstraintIndices
        )
        self.TechOutputSplitConstraint = Constraint(
            self.TechOutputSplitConstraint_rpsdtvo, rule=TechOutputSplit_Constraint
        )

        self.TechOutputSplitAnnualConstraint_rptvo = Set(
            dimen=5, initialize=TechOutputSplitAnnualConstraintIndices
        )
        self.TechOutputSplitAnnualConstraint = Constraint(
            self.TechOutputSplitAnnualConstraint_rptvo, rule=TechOutputSplitAnnual_Constraint
        )
        self.LinkedEmissionsTechConstraint_rpsdtve = Set(dimen=7, initialize=LinkedTechConstraintIndices)
        self.LinkedEmissionsTechConstraint = Constraint(
            self.LinkedEmissionsTechConstraint_rpsdtve, rule=LinkedEmissionsTech_Constraint)

        logger.info('TemoaModel AbstractModel built')

        # if "__main__" == __name__:
        #     """This code only invoked when called this file is invoked directly from the
        #     command line as follows: $ python temoa_model/temoa_model.py path/to/dat/file"""
        #
        #     dummy = ""  # If calling from command line, send empty string
        #     model = runModel()
