"""
tool for writing outputs to database tables
"""
import sqlite3
import sys
from collections import defaultdict, namedtuple
from logging import getLogger
from typing import TYPE_CHECKING

from pyomo.core import value

from temoa.temoa_model import temoa_rules
from temoa.temoa_model.exchange_tech_cost_ledger import CostType, ExchangeTechCostLedger
from temoa.temoa_model.temoa_config import TemoaConfig
from temoa.temoa_model.temoa_mode import TemoaMode
from temoa.temoa_model.temoa_model import TemoaModel

if TYPE_CHECKING:
    pass

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


Written by:  J. F. Hyink
jeff@westernspark.us
https://westernspark.us
Created on:  2/9/24

Note:  This file borrows heavily from the legacy pformat_results.py, and is somewhat of a restructure of that code
       to accommodate the run modes more cleanly

"""

logger = getLogger(__name__)

scenario_based_tables = [
    'OutputCost',
]

EI = namedtuple('EI', ['r', 'p', 't', 'v', 'e'])


class TableWriter:
    def __init__(self, config: TemoaConfig, epsilon=1e-5):
        self.config = config
        self.epsilon = epsilon
        try:
            self.con = sqlite3.connect(config.output_database)
        except sqlite3.OperationalError as e:
            logger.error('Failed to connect to output database: %s', config.output_database)
            logger.error(e)
            sys.exit(-1)

    def clear_scenario(self):
        cur = self.con.cursor()
        for table in scenario_based_tables:
            cur.execute(f'DELETE FROM {table} WHERE scenario = ?', (self.config.scenario,))
        self.con.commit()

    def write_objective(self):
        pass
        # objs = list(m.component_data_objects(Objective))
        # if len(objs) > 1:
        #     msg = '\nWarning: More than one objective.  Using first objective.\n'
        #     SE.write(msg)
        # # This is a generic workaround.  Not sure how else to automatically discover
        # # the objective name
        # obj_name, obj_value = objs[0].getname(True), value(objs[0])
        # svars['Objective']["('" + obj_name + "')"] = obj_value

    @staticmethod
    def loan_costs(
        loan_rate,  # this is referred to as LoanRate in parameters
        loan_life,
        capacity,
        invest_cost,
        process_life,
        p_0,
        p_e,
        global_discount_rate,
        vintage,
        **kwargs,
    ) -> tuple[float, float]:
        """
        Calculate Loan costs by calling the loan annualize and loan cost functions in temoa_rules
        :return: tuple of [model-view discounted cost, un-discounted annuity]
        """
        loan_ar = temoa_rules.loan_annualization_rate(loan_rate=loan_rate, loan_life=loan_life)
        model_ic = temoa_rules.loan_cost(
            capacity,
            invest_cost,
            loan_annualize=loan_ar,
            lifetime_loan_process=loan_life,
            lifetime_process=process_life,
            P_0=p_0,
            P_e=p_e,
            GDR=global_discount_rate,
            vintage=vintage,
        )
        # Override the GDR to get the undiscounted value
        global_discount_rate = 0
        undiscounted_cost = temoa_rules.loan_cost(
            capacity,
            invest_cost,
            loan_annualize=loan_ar,
            lifetime_loan_process=loan_life,
            lifetime_process=process_life,
            P_0=p_0,
            P_e=p_e,
            GDR=global_discount_rate,
            vintage=vintage,
        )
        return model_ic, undiscounted_cost

    def write_costs(self, M: TemoaModel):
        """
        Gather the cost data vars
        :param M: the Temoa Model
        :return: dictionary of results of format variable name -> {idx: value}
        """

        # P_0 is usually the first optimization year, but if running myopic, we could assign it via
        # table entry.  Perhaps in future it is just always the first optimization year of the 1st iter.
        if self.config.scenario_mode == TemoaMode.MYOPIC:
            p_0 = M.MyopicBaseyear
        else:
            p_0 = min(M.time_optimize)
        # NOTE:  The end period in myopic mode is specific to the window / MyopicIndex
        #        the time_future set is specific to the window
        p_e = M.time_future.last()

        # conveniences...
        GDR = value(M.GlobalDiscountRate)
        MPL = M.ModelProcessLife
        LLN = M.LifetimeLoanProcess

        exchange_costs = ExchangeTechCostLedger(M)
        entries = defaultdict(dict)
        for r, t, v in M.CostInvest.sparse_iterkeys():  # Returns only non-zero values
            # gather details...
            cap = value(M.V_NewCapacity[r, t, v])
            if abs(cap) < self.epsilon:
                continue
            loan_life = value(LLN[r, t, v])
            loan_rate = value(M.LoanRate[r, t, v])

            model_loan_cost, undiscounted_cost = self.loan_costs(
                loan_rate=value(M.LoanRate[r, t, v]),
                loan_life=loan_life,
                capacity=cap,
                invest_cost=value(M.CostInvest[r, t, v]),
                process_life=value(M.LifetimeProcess[r, t, v]),
                p_0=p_0,
                p_e=p_e,
                global_discount_rate=GDR,
                vintage=v,
            )
            # screen for linked region...
            if '-' in r:
                exchange_costs.add_cost_record(
                    r,
                    period=v,
                    tech=t,
                    vintage=v,
                    cost=model_loan_cost,
                    cost_type=CostType.D_INVEST,
                )
                exchange_costs.add_cost_record(
                    r,
                    period=v,
                    tech=t,
                    vintage=v,
                    cost=undiscounted_cost,
                    cost_type=CostType.INVEST,
                )
            else:
                # enter it into the entries table with period of cost = vintage (p=v)
                entries[r, v, t, v].update(
                    {CostType.D_INVEST: model_loan_cost, CostType.INVEST: undiscounted_cost}
                )

        for r, p, t, v in M.CostFixed.sparse_iterkeys():
            cap = value(M.V_Capacity[r, p, t, v])
            if abs(cap) < self.epsilon:
                continue

            fixed_cost = value(M.CostFixed[r, p, t, v])
            undiscounted_fixed_cost = cap * fixed_cost * value(MPL[r, p, t, v])

            model_fixed_cost = temoa_rules.fixed_or_variable_cost(
                cap, fixed_cost, value(MPL[r, p, t, v]), GDR=GDR, P_0=p_0, p=p
            )
            if '-' in r:
                exchange_costs.add_cost_record(
                    r,
                    period=p,
                    tech=t,
                    vintage=v,
                    cost=model_fixed_cost,
                    cost_type=CostType.D_FIXED,
                )
                exchange_costs.add_cost_record(
                    r,
                    period=p,
                    tech=t,
                    vintage=v,
                    cost=undiscounted_fixed_cost,
                    cost_type=CostType.FIXED,
                )
            else:
                entries[r, p, t, v].update(
                    {CostType.D_FIXED: model_fixed_cost, CostType.FIXED: undiscounted_fixed_cost}
                )

        for r, p, t, v in M.CostVariable.sparse_iterkeys():
            if t not in M.tech_annual:
                activity = sum(
                    value(M.V_FlowOut[r, p, S_s, S_d, S_i, t, v, S_o])
                    for S_i in M.processInputs[r, p, t, v]
                    for S_o in M.ProcessOutputsByInput[r, p, t, v, S_i]
                    for S_s in M.time_season
                    for S_d in M.time_of_day
                )
            else:
                activity = sum(
                    value(M.V_FlowOutAnnual[r, p, S_i, t, v, S_o])
                    for S_i in M.processInputs[r, p, t, v]
                    for S_o in M.ProcessOutputsByInput[r, p, t, v, S_i]
                )
            if abs(activity) < self.epsilon:
                continue

            var_cost = value(M.CostVariable[r, p, t, v])
            undiscounted_var_cost = activity * var_cost * value(MPL[r, p, t, v])

            model_var_cost = temoa_rules.fixed_or_variable_cost(
                activity, var_cost, value(MPL[r, p, t, v]), GDR=GDR, P_0=p_0, p=p
            )
            if '-' in r:
                exchange_costs.add_cost_record(
                    r,
                    period=p,
                    tech=t,
                    vintage=v,
                    cost=model_var_cost,
                    cost_type=CostType.D_VARIABLE,
                )
                exchange_costs.add_cost_record(
                    r,
                    period=p,
                    tech=t,
                    vintage=v,
                    cost=undiscounted_var_cost,
                    cost_type=CostType.VARIABLE,
                )
            else:
                entries[r, p, t, v].update(
                    {CostType.D_VARIABLE: model_var_cost, CostType.VARIABLE: undiscounted_var_cost}
                )
        emission_entries = self._gather_emission_costs(M)
        for k in emission_entries.keys():
            entries[k].update(emission_entries[k])
        # write to table
        # translate the entries into fodder for the query
        self.write_rows(entries)
        self.write_rows(exchange_costs.get_entries())

    def _gather_emission_costs(self, M: 'TemoaModel'):
        """there are 5 'flavors' of emission costs.  So, we need to gather the base and then decide on each"""
        GDR = value(M.GlobalDiscountRate)
        MPL = M.ModelProcessLife
        if self.config.scenario_mode == TemoaMode.MYOPIC:
            p_0 = M.MyopicBaseyear
        else:
            p_0 = min(M.time_optimize)

        base = [
            (r, p, e, i, t, v, o)
            for (r, e, i, t, v, o) in M.EmissionActivity
            for p in M.time_optimize
            if (r, p, e) in M.CostEmission  # tightest filter first
            and (r, p, t, v) in M.processInputs
        ]
        normal = [
            (r, p, e, s, d, i, t, v, o)
            for (r, p, e, i, t, v, o) in base
            for s in M.time_season
            for d in M.time_of_day
            if t not in M.tech_annual
        ]
        annual = [(r, p, e, i, t, v, o) for (r, p, e, i, t, v, o) in base if t in M.tech_annual]

        flow: dict[EI, float] = defaultdict(float)
        # iterate through the normal and annual and accumulate flow values
        for r, p, e, s, d, i, t, v, o in normal:
            if t in M.tech_curtailment:
                flow[EI(r, p, t, v, e)] += (
                    value(M.V_Curtailment[r, p, s, d, i, t, v, o])
                    * M.EmissionActivity[r, e, i, t, v, o]
                )
            elif t in M.tech_flex:
                flow[EI(r, p, t, v, e)] += (
                    value(M.V_Flex[r, p, s, d, i, t, v, o]) * M.EmissionActivity[r, e, i, t, v, o]
                )
            else:
                flow[EI(r, p, t, v, e)] += (
                    value(M.V_FlowOut[r, p, s, d, i, t, v, o])
                    * M.EmissionActivity[r, e, i, t, v, o]
                )
        for r, p, e, i, t, v, o in annual:
            if t in M.tech_flex and o in M.flex_commodities:
                flow[EI(r, p, t, v, e)] += (
                    value(M.V_FlexAnnual[r, p, i, t, v, o]) * M.EmissionActivity[r, e, i, t, v, o]
                )
            else:
                flow[EI(r, p, t, v, e)] += (
                    value(M.V_FlowOutAnnual[r, p, i, t, v, o])
                    * M.EmissionActivity[r, e, i, t, v, o]
                )

        ud_costs = defaultdict(float)
        d_costs = defaultdict(float)
        for ei in flow:
            if flow[ei] < self.epsilon:
                continue
            undiscounted_emiss_cost = (
                flow[ei] * M.CostEmission[ei.r, ei.p, ei.e] * MPL[ei.r, ei.p, ei.t, ei.v]
            )
            discounted_emiss_cost = temoa_rules.fixed_or_variable_cost(
                cap_or_flow=flow[ei],
                cost_factor=M.CostEmission[ei.r, ei.p, ei.e],
                process_lifetime=MPL[ei.r, ei.p, ei.t, ei.v],
                GDR=GDR,
                P_0=p_0,
                p=ei.p,
            )
            ud_costs[ei.r, ei.p, ei.t, ei.v] += undiscounted_emiss_cost
            d_costs[ei.r, ei.p, ei.t, ei.v] += discounted_emiss_cost
        entries = defaultdict(dict)
        for k in ud_costs:
            entries[k][CostType.EMISS] = ud_costs[k]
        for k in d_costs:
            entries[k][CostType.D_EMISS] = d_costs[k]

        # wow, that was like pulling teeth
        return entries

    def write_rows(self, entries):
        rows = [
            (
                self.config.scenario,
                r,
                p,
                t,
                v,
                entries[r, p, t, v].get(CostType.D_INVEST, 0),
                entries[r, p, t, v].get(CostType.D_FIXED, 0),
                entries[r, p, t, v].get(CostType.D_VARIABLE, 0),
                entries[r, p, t, v].get(CostType.D_EMISS, 0),
                entries[r, p, t, v].get(CostType.INVEST, 0),
                entries[r, p, t, v].get(CostType.FIXED, 0),
                entries[r, p, t, v].get(CostType.VARIABLE, 0),
                entries[r, p, t, v].get(CostType.EMISS, 0),
            )
            for (r, p, t, v) in entries
        ]
        # let's be kind and sort by something reasonable (r, v, t, p)
        rows.sort(key=lambda r: (r[1], r[4], r[3], r[2]))
        # TODO:  maybe extract this to a pure writing function...we shall see
        cur = self.con.cursor()
        qry = 'INSERT INTO OutputCost VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
        cur.executemany(qry, rows)
        self.con.commit()

    def __del__(self):
        if self.con:
            self.con.close()
