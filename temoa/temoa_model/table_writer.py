"""
tool for writing outputs to database tables
"""
from collections import defaultdict
from logging import getLogger
from sqlite3 import Connection

from pyomo.core import value

from temoa.temoa_model import temoa_rules
from temoa.temoa_model.temoa_config import TemoaConfig
from temoa.temoa_model.temoa_mode import TemoaMode
from temoa.temoa_model.temoa_model import TemoaModel

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


class TableWriter:
    def __init__(
        self,
        config: TemoaConfig,
        db_con: Connection,
        epsilon=1e-5,
    ):
        self.config = config
        self.epsilon = epsilon
        self.con = db_con

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
        loan_rate,
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
        Calculate Loan costs
        :return: tuple of [model-view discounted cost, un-discounted annuity]
        """
        loan_ar = temoa_rules.loan_annualization_rate(discount_rate=loan_rate, loan_life=loan_life)
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

    def write_costs(self, m: TemoaModel):
        """
        Gather the cost data vars
        :param m: the Temoa Model
        :param epsilon: cutoff to ignore as zero
        :param myopic_iteration: True if the iteration is myopic
        :return: dictionary of results of format variable name -> {idx: value}
        """

        # P_0 is usually the first optimization year, but if running myopic, we could assign it via
        # table entry.  Perhaps in future it is just always the first optimization year of the 1st iter.
        if self.config.scenario_mode == TemoaMode.MYOPIC:
            p_0 = m.MyopicBaseyear
        else:
            p_0 = min(m.time_optimize)
        # NOTE:  The end period in myopic mode is specific to the window / MyopicIndex
        p_e = m.time_future.last()

        # conveniences...
        GDR = value(m.GlobalDiscountRate)
        MPL = m.ModelProcessLife
        LLN = m.LifetimeLoanProcess

        entries = defaultdict(dict)
        for r, t, v in m.CostInvest.sparse_iterkeys():  # Returns only non-zero values
            # gather details...
            cap = value(m.V_NewCapacity[r, t, v])
            if abs(cap) < self.epsilon:
                continue
            loan_life = value(LLN[r, t, v])
            loan_rate = value(m.DiscountRate[r, t, v])

            model_loan_cost, undiscounted_cost = self.loan_costs(
                loan_rate=value(m.DiscountRate[r, t, v]),
                loan_life=loan_life,
                capacity=cap,
                invest_cost=value(m.CostInvest[r, t, v]),
                process_life=value(m.LifetimeProcess[r, t, v]),
                p_0=p_0,
                p_e=p_e,
                global_discount_rate=GDR,
                vintage=v,
            )
            # enter it into the entries table with period of cost = vintage (p=v)
            entries[r, v, t, v].update({'invest_m': model_loan_cost, 'invest': undiscounted_cost})

        for r, p, t, v in m.CostFixed.sparse_iterkeys():
            cap = value(m.V_Capacity[r, p, t, v])
            if abs(cap) < self.epsilon:
                continue

            fixed_cost = value(m.CostFixed[r, p, t, v])
            undiscounted_fixed_cost = cap * fixed_cost * value(MPL[r, p, t, v])

            model_fixed_cost = temoa_rules.fixed_or_variable_cost(
                cap, fixed_cost, value(MPL[r, p, t, v]), GDR=GDR, P_0=p_0, p=p
            )
            entries[r, p, t, v].update(
                {'fixed_m': model_fixed_cost, 'fixed': undiscounted_fixed_cost}
            )

        for r, p, t, v in m.CostVariable.sparse_iterkeys():
            if t not in m.tech_annual:
                activity = sum(
                    value(m.V_FlowOut[r, p, S_s, S_d, S_i, t, v, S_o])
                    for S_i in m.processInputs[r, p, t, v]
                    for S_o in m.ProcessOutputsByInput[r, p, t, v, S_i]
                    for S_s in m.time_season
                    for S_d in m.time_of_day
                )
            else:
                activity = sum(
                    value(m.V_FlowOutAnnual[r, p, S_i, t, v, S_o])
                    for S_i in m.processInputs[r, p, t, v]
                    for S_o in m.ProcessOutputsByInput[r, p, t, v, S_i]
                )
            if abs(activity) < self.epsilon:
                continue

            var_cost = value(m.CostVariable[r, p, t, v])
            undiscounted_var_cost = activity * var_cost * value(MPL[r, p, t, v])

            model_var_cost = temoa_rules.fixed_or_variable_cost(
                activity, var_cost, value(MPL[r, p, t, v]), GDR=GDR, P_0=p_0, p=p
            )
            entries[r, p, t, v].update({'var_m': model_var_cost, 'var': undiscounted_var_cost})

        # write to table
        # translate the entries into fodder for the query
        rows = [
            (
                self.config.scenario,
                r,
                p,
                t,
                v,
                round(entries[r, p, t, v].get('invest_m', 0), 2),
                round(entries[r, p, t, v].get('fixed_m', 0), 2),
                round(entries[r, p, t, v].get('var_m', 0), 2),
                round(entries[r, p, t, v].get('invest', 0), 2),
                round(entries[r, p, t, v].get('fixed', 0), 2),
                round(entries[r, p, t, v].get('var', 0), 2),
            )
            for (r, p, t, v) in entries
        ]
        # TODO:  maybe extract this to a pure writing function...we shall see
        cur = self.con.cursor()
        qry = 'INSERT INTO Output_Costs_2 VALUES (?,  ?, ?, ?, ?, ?, ?, ?, ?, ?, ? )'
        cur.executemany(qry, rows)
        self.con.commit()

        # dev note:  This is somewhat complex for exchange technologies...
        # In the model, a capacity variable is created for BOTH direction on an exchange, and each direction needs to be
        # defined separately in the dataset (Efficiency).
        # Due to fact that both direction capacity var
