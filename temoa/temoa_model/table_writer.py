"""
tool for writing outputs to database tables
"""
from collections import defaultdict
from enum import Enum, unique
from logging import getLogger
from sqlite3 import Connection
from typing import TYPE_CHECKING, Union

from pyomo.core import value

from temoa.temoa_model import temoa_rules
from temoa.temoa_model.temoa_config import TemoaConfig
from temoa.temoa_model.temoa_mode import TemoaMode
from temoa.temoa_model.temoa_model import TemoaModel

if TYPE_CHECKING:
    from tests.test_exchange_cost_ledger import Namespace

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
    'Output_Costs_2',
]


@unique
class CostType(Enum):
    INVEST = 1
    FIXED = 2
    VARIABLE = 3
    D_INVEST = 4
    D_FIXED = 5
    D_VARIABLE = 6


class ExchangeTechCostLedger:
    def __init__(self, M: Union[TemoaModel, 'Namespace']) -> None:
        self.cost_records: dict[CostType, dict] = defaultdict(dict)
        # could be a Namespace for testing purposes...  See the related test
        self.M = M

    def add_cost_record(self, link: str, period, tech, vintage, cost: float, cost_type: CostType):
        """
        add a cost associated with an exchange tech
        :return:
        """
        r1, r2 = link.split('-')
        if not r1 and r2:
            raise ValueError(f'problem splitting region-region: {link}')
        # add to the "seen" records for appropriate cost type
        self.cost_records[cost_type][r1, r2, tech, vintage, period] = cost

    def get_use_ratio(self, exporter, importer, period, tech, vintage) -> float:
        """
        use flow to calculate the use ratio for these 2 entities for cost apportioning purposes
        :param exporter:
        :param importer:
        :param period:
        :param tech:
        :param vintage:
        :return: the proportion to assign to the IMPORTER, or 0.5 if no usage
        """
        M = self.M
        # need to temporarily reconstitute the names
        rr1 = '-'.join([exporter, importer])
        rr2 = '-'.join([importer, exporter])
        if any(
            (
                period >= vintage + value(M.LifetimeProcess[rr1, tech, vintage]),
                period >= vintage + value(M.LifetimeProcess[rr2, tech, vintage]),
                period < vintage,
            )
        ):
            raise ValueError(f'received a bogus cost for an illegal period.')
        if tech not in M.tech_annual:
            act_dir1 = value(
                sum(
                    M.V_FlowOut[rr1, period, s, d, S_i, tech, vintage, S_o]
                    for s in M.time_season
                    for d in M.time_of_day
                    for S_i in M.processInputs[rr1, period, tech, vintage]
                    for S_o in M.ProcessOutputsByInput[rr1, period, tech, vintage, S_i]
                )
            )
            act_dir2 = value(
                sum(
                    M.V_FlowOut[rr2, period, s, d, S_i, tech, vintage, S_o]
                    for s in M.time_season
                    for d in M.time_of_day
                    for S_i in M.processInputs[rr2, period, tech, vintage]
                    for S_o in M.ProcessOutputsByInput[rr2, period, tech, vintage, S_i]
                )
            )
        else:
            act_dir1 = value(
                sum(
                    M.V_FlowOutAnnual[rr1, period, S_i, tech, vintage, S_o]
                    for S_i in M.processInputs[rr1, period, tech, vintage]
                    for S_o in M.ProcessOutputsByInput[rr1, period, tech, vintage, S_i]
                )
            )
            act_dir2 = value(
                sum(
                    M.V_FlowOutAnnual[rr2, period, S_i, tech, vintage, S_o]
                    for S_i in M.processInputs[rr2, period, tech, vintage]
                    for S_o in M.ProcessOutputsByInput[rr2, period, tech, vintage, S_i]
                )
            )

        if act_dir1 + act_dir2 > 0:
            return act_dir1 / (act_dir1 + act_dir2)
        return 0.5

    def get_entries(self) -> dict:
        region_costs = defaultdict(dict)
        # iterate through each region pairing, pull the cost records and decide if/how to split each one
        for cost_type in self.cost_records:
            # make a copy, this will be destructive operation
            records = self.cost_records[cost_type].copy()
            while records:
                (r1, r2, tech, vintage, period), cost = records.popitem()  # pops a random item
                # try to get the partner (reversed regions), if it exists
                partner_cost = records.pop((r2, r1, tech, vintage, period), None)
                if (
                    partner_cost
                ):  # they are both entered, so we just record the costs... no splitting
                    region_costs[r2, period, tech, vintage].update({cost_type: cost})
                    region_costs[r1, period, tech, vintage].update({cost_type: partner_cost})
                else:
                    # only one side had costs: the signal to split based on use
                    use_ratio = self.get_use_ratio(r1, r2, period, tech, vintage)
                    # not r2 is the "importer" and that is the ratio assignment
                    region_costs[r1, period, tech, vintage].update(
                        {cost_type: cost * (1.0 - use_ratio)}
                    )
                    region_costs[r2, period, tech, vintage].update({cost_type: cost * use_ratio})

        return region_costs


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
        loan_rate,  # this is referred to as DiscountRate in parameters
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
            loan_rate = value(M.DiscountRate[r, t, v])

            model_loan_cost, undiscounted_cost = self.loan_costs(
                loan_rate=value(M.DiscountRate[r, t, v]),
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
                    r, period=p, tech=t, vintage=v, cost=fixed_cost, cost_type=CostType.D_FIXED
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
                    r, period=p, tech=t, vintage=v, cost=var_cost, cost_type=CostType.D_VARIABLE
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

        # write to table
        # translate the entries into fodder for the query
        self.write_rows(entries)
        self.write_rows(exchange_costs.get_entries())

    def write_rows(self, entries):
        rows = [
            (
                self.config.scenario,
                r,
                p,
                t,
                v,
                round(entries[r, p, t, v].get(CostType.D_INVEST, 0), 2),
                round(entries[r, p, t, v].get(CostType.D_FIXED, 0), 2),
                round(entries[r, p, t, v].get(CostType.D_VARIABLE, 0), 2),
                round(entries[r, p, t, v].get(CostType.INVEST, 0), 2),
                round(entries[r, p, t, v].get(CostType.FIXED, 0), 2),
                round(entries[r, p, t, v].get(CostType.VARIABLE, 0), 2),
            )
            for (r, p, t, v) in entries
        ]
        # let's be kind and sort by something reasonable (r, v, t, p)
        rows.sort(key=lambda r: (r[1], r[4], r[3], r[2]))
        # TODO:  maybe extract this to a pure writing function...we shall see
        cur = self.con.cursor()
        qry = 'INSERT INTO Output_Costs_2 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
        cur.executemany(qry, rows)
        self.con.commit()
