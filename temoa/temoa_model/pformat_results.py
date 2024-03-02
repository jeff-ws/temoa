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

# ---------------------------------------------------------------------------
# This module processes model output data, which can be sent to three possible
# locations: the shell, a user-specified database, or an Excel file. Users can
# configure the available outputs.
# ---------------------------------------------------------------------------


__all__ = ('pformat_results', 'stringify_data')

import os
import re
import sqlite3
from collections import defaultdict
from io import StringIO
from logging import getLogger
from shutil import rmtree
from sys import stderr as SE, stdout as SO

import pandas as pd
from pyomo.core import Objective
from pyomo.environ import value
from pyomo.opt import SolverResults

from temoa.data_processing.DB_to_Excel import make_excel
from temoa.temoa_model.temoa_config import TemoaConfig
from temoa.temoa_model.temoa_mode import TemoaMode

logger = getLogger(__name__)


def stringify_data(data, ostream=SO, format='plain'):
    # data is a list of tuples of ('var_name[index]', value)
    #  data must be a list, as this function replaces each row,
    # format is currently unused, but will be utilized to implement things like
    # csv

    # This padding code is what makes the display of the output values
    # line up on the decimal point.
    for i, (v, val) in enumerate(data):
        ipart, fpart = repr(f"{val:.6f}").split('.')
        data[i] = (ipart, fpart, v)
    cell_lengths = (map(len, l[:-1]) for l in data)
    max_lengths = map(max, zip(*cell_lengths))  # max length of each column
    fmt = u'  {{:>{:d}}}.{{:<{:d}}}  {{}}\n'.format(*max_lengths)

    for row in data:
        ostream.write(fmt.format(*row))


def collect_result_data(cgroup, epsilon, scenario_name: str | None = None):
    # TODO:  This needs a cleanup.  dox, use of pandas, dictionary/list/dataframe??
    #        The logic of not doing anything if there is no scenario name, etc...
    #        And it should probably be more than 1 function

    # cgroup = "Component group"; i.e., Vars or Cons
    # clist = "Component list"; i.e., where to store the data
    # epsilon = absolute value below which to ignore a result
    result_list = []
    results = defaultdict(list)
    for name, data in cgroup.items():
        if 'Value' not in data.keys() or (abs(data['Value']) < epsilon): continue

        # TODO: this portion is not used because we are only sending constraints here to get duals and constraints don't
        #       have value.... this is dead code, but perhaps hints at a better approach using pandas?

        # name looks like "Something[some,index]"
        group, index = name[:-1].split('[')
        results[group].append((name.replace("'", ''), data['Value']))
    result_list.extend(t for i in sorted(results) for t in sorted(results[i]))

    supp_outputs_df = pd.DataFrame.from_dict(cgroup, orient='index')
    supp_outputs_df = supp_outputs_df.loc[(supp_outputs_df != 0).any(axis=1)]
    if 'Dual' in supp_outputs_df.columns:
        duals = supp_outputs_df['Dual'].copy()
        duals = duals[abs(duals) > 1e-5]
        duals.index.name = 'constraint_name'
        duals = duals.to_frame()
        if scenario_name and len(duals) > 0:
            duals.loc[:, 'scenario'] = scenario_name
            return result_list, duals
        else:
            return result_list, []


def gather_variable_data(m: 'TemoaModel', epsilon: float, capacity_epsilon: float,
                         myopic_iteration=False) -> dict[
    str, dict[tuple[str, ...], float]]:
    """
    Gather the variable values from the necessary model items into a dictionary
    :param myopic_iteration: True if this iteration is myopic
    :param m: the solved instance
    :param epsilon: an epsilon value for non-capacity variables to distinguish from zero
    :param capacity_epsilon: an epsilon value for capacity variables
    :return: dictionary of results of format variable name -> {idx: value}
    """
    # Create a dictionary in which to store "solved" variable values
    svars = defaultdict(lambda: defaultdict(float))
    # Extract optimal decision variable values related to commodity flow:
    for r, p, s, d, t, v in m.V_StorageLevel:
        val = value(m.V_StorageLevel[r, p, s, d, t, v])
        if abs(val) < epsilon: continue

        svars['V_StorageLevel'][r, p, s, d, t, v] = val

    # vflow_in is defined only for storage techs
    for r, p, s, d, i, t, v, o in m.V_FlowIn:
        val_in = value(m.V_FlowIn[r, p, s, d, i, t, v, o])
        if abs(val_in) < epsilon: continue

        svars['V_FlowIn'][r, p, s, d, i, t, v, o] = val_in

    # we need to pre-identify the keys for emissions to pluck them out in the course of
    # inspecting the flows below...
    emission_keys = {(r, i, t, v, o): set() for r, e, i, t, v, o in m.EmissionActivity}
    for r, e, i, t, v, o in m.EmissionActivity:
        emission_keys[(r, i, t, v, o)].add(e)

    for r, p, s, d, i, t, v, o in m.V_FlowOut:
        val_out = value(m.V_FlowOut[r, p, s, d, i, t, v, o])
        if abs(val_out) < epsilon: continue

        svars['V_FlowOut'][r, p, s, d, i, t, v, o] = val_out

        if t not in m.tech_storage:
            val_in = value(m.V_FlowOut[r, p, s, d, i, t, v, o]) / value(m.Efficiency[r, i, t, v, o])
            svars['V_FlowIn'][r, p, s, d, i, t, v, o] = val_in

        if (r, i, t, v, o) not in emission_keys: continue

        emissions = emission_keys[r, i, t, v, o]
        for e in emissions:
            evalue = val_out * m.EmissionActivity[r, e, i, t, v, o]
            svars['V_EmissionActivityByPeriodAndProcess'][r, p, e, t, v] += evalue

    for r, p, i, t, v, o in m.V_FlowOutAnnual:
        for s in m.time_season:
            for d in m.time_of_day:
                val_out = value(m.V_FlowOutAnnual[r, p, i, t, v, o]) * value(m.SegFrac[s, d])
                if abs(val_out) < epsilon: continue
                svars['V_FlowOut'][r, p, s, d, i, t, v, o] = val_out
                svars['V_FlowIn'][r, p, s, d, i, t, v, o] = val_out / value(
                    m.Efficiency[r, i, t, v, o])
                if (r, i, t, v, o) not in emission_keys: continue
                emissions = emission_keys[r, i, t, v, o]
                for e in emissions:
                    evalue = val_out * m.EmissionActivity[r, e, i, t, v, o]
                    svars['V_EmissionActivityByPeriodAndProcess'][r, p, e, t, v] += evalue

    for r, p, s, d, i, t, v, o in m.V_Curtailment:
        val = value(m.V_Curtailment[r, p, s, d, i, t, v, o])
        if abs(val) < epsilon: continue
        svars['V_Curtailment'][r, p, s, d, i, t, v, o] = val
        svars['V_FlowIn'][r, p, s, d, i, t, v, o] = (val + value(
            m.V_FlowOut[r, p, s, d, i, t, v, o])) / value(
            m.Efficiency[r, i, t, v, o])

        if (r, i, t, v, o) not in emission_keys: continue

        emissions = emission_keys[r, i, t, v, o]
        for e in emissions:
            evalue = val * m.EmissionActivity[r, e, i, t, v, o]
            svars['V_EmissionActivityByPeriodAndProcess'][r, p, e, t, v] += evalue

    for r, p, i, t, v, o in m.V_FlexAnnual:
        for s in m.time_season:
            for d in m.time_of_day:
                val_out = value(m.V_FlexAnnual[r, p, i, t, v, o]) * value(m.SegFrac[s, d])
                if abs(val_out) < epsilon: continue
                svars['V_Curtailment'][r, p, s, d, i, t, v, o] = val_out
                svars['V_FlowOut'][r, p, s, d, i, t, v, o] -= val_out

    for r, p, s, d, i, t, v, o in m.V_Flex:
        val_out = value(m.V_Flex[r, p, s, d, i, t, v, o])
        if abs(val_out) < epsilon: continue
        svars['V_Curtailment'][r, p, s, d, i, t, v, o] = val_out
        svars['V_FlowOut'][r, p, s, d, i, t, v, o] -= val_out

    # Extract optimal decision variable values related to capacity:
    if not myopic_iteration:
        for r, p, t, v in m.V_Capacity:
            val = value(m.V_Capacity[r, p, t, v])
            if abs(val) < capacity_epsilon: continue
            svars['V_Capacity'][r, p, t, v] = val
    else:
        for r, p, t, v in m.V_Capacity:
            if p in m.time_optimize:
                val = value(m.V_Capacity[r, p, t, v])
                if abs(val) < capacity_epsilon: continue
                svars['V_Capacity'][r, p, t, v] = val

    if not myopic_iteration:
        for r, t, v in m.V_NewCapacity:
            val = value(m.V_NewCapacity[r, t, v])
            if abs(val) < capacity_epsilon: continue
            svars['V_NewCapacity'][r, t, v] = val
    else:
        for r, t, v in m.V_NewCapacity:
            if v in m.time_optimize:
                val = value(m.V_NewCapacity[r, t, v])
                if abs(val) < capacity_epsilon: continue
                svars['V_NewCapacity'][r, t, v] = val

    if not myopic_iteration:
        for r, p, t, v in m.V_RetiredCapacity:
            val = value(m.V_RetiredCapacity[r, p, t, v])
            if abs(val) < capacity_epsilon: continue
            svars['V_RetiredCapacity'][r, p, t, v] = val
    else:
        for r, p, t, v in m.V_RetiredCapacity:
            if p in m.time_optimize:
                val = value(m.V_RetiredCapacity[r, p, t, v])
                if abs(val) < capacity_epsilon: continue
                svars['V_RetiredCapacity'][r, p, t, v] = val

    for r, p, t in m.V_CapacityAvailableByPeriodAndTech:
        val = value(m.V_CapacityAvailableByPeriodAndTech[r, p, t])
        if abs(val) < epsilon: continue
        svars['V_CapacityAvailableByPeriodAndTech'][r, p, t] = val

    return svars


def gather_cost_data(m: 'TemoaModel', epsilon: float, myopic_iteration) -> dict[
    str, dict[tuple[str, ...], float]]:
    """
    Gather the cost data vars
    :param m: the Temoa Model
    :param epsilon: cutoff to ignore as zero
    :param myopic_iteration: True if the iteration is myopic
    :return: dictionary of results of format variable name -> {idx: value}
    """

    svars = defaultdict(lambda: defaultdict(float))
    P_0 = min(m.time_optimize)
    P_e = m.time_future.last()
    GDR = value(m.GlobalDiscountRate)
    MPL = m.ModelProcessLife
    LLN = m.LifetimeLoanProcess
    rate = 1 + GDR  # convenience variable, nothing more

    # this block seems nonsensical.  If it is read, it is ignored below by the other if statement
    if myopic_iteration:
        pass
        # original_dbpath = config.output_database
        # con = sqlite3.connect(original_dbpath)
        # cur = con.cursor()
        # time_periods = cur.execute("SELECT t_periods FROM time_periods WHERE flag='f'").fetchall()
        # P_0 = time_periods[0][0]
        # P_e = time_periods[-1][0]
        # # We need to know if a myopic run is the last run or not.
        # P_e_time_optimize = time_periods[-2][0]
        # P_e_current = int(config.file_location.split("_")[-1])
        # con.commit()
        # con.close()

    # Calculate model costs:
    # TODO:  The 'file_location' variable in the old config was the path to the config file, and it was used
    #        to key some operations (as below) and also to determine the running mode (myopic or not)

    # dev note:  This is somewhat complex for exchange technologies...
    # In the model, a capacity variable is created for BOTH direction on an exchange, and each direction needs to be
    # defined separately in the dataset (Efficiency).
    # Due to fact that both direction capacity var
    if not myopic_iteration:
        objs = list(m.component_data_objects(Objective))
        if len(objs) > 1:
            msg = '\nWarning: More than one objective.  Using first objective.\n'
            SE.write(msg)
        # This is a generic workaround.  Not sure how else to automatically discover
        # the objective name
        obj_name, obj_value = objs[0].getname(True), value(objs[0])
        svars['Objective']["('" + obj_name + "')"] = obj_value

        for r, t, v in m.CostInvest.sparse_iterkeys():  # Returns only non-zero values

            icost = value(m.V_NewCapacity[r, t, v])
            if abs(icost) < epsilon: continue
            icost *= value(m.CostInvest[r, t, v]) * (
                    (
                            1 - rate ** (-min(value(m.LifetimeProcess[r, t, v]), P_e - v))
                    ) / (
                            1 - rate ** (-value(m.LifetimeProcess[r, t, v]))
                    )
            )
            svars['Costs']['V_UndiscountedInvestmentByProcess', r, t, v] += icost

            icost *= value(m.LoanAnnualize[r, t, v])
            icost *= (
                value(LLN[r, t, v]) if not GDR else
                (rate ** (P_0 - v + 1) * (1 - rate ** (-value(LLN[r, t, v]))) / GDR)
            )

            svars['Costs']['V_DiscountedInvestmentByProcess', r, t, v] += icost

        for r, p, t, v in m.CostFixed.sparse_iterkeys():
            fcost = value(m.V_Capacity[r, p, t, v])
            if abs(fcost) < epsilon: continue

            fcost *= value(m.CostFixed[r, p, t, v])
            svars['Costs']['V_UndiscountedFixedCostsByProcess', r, t, v] += fcost * value(
                MPL[r, p, t, v])

            fcost *= (
                value(MPL[r, p, t, v]) if not GDR else
                (rate ** (P_0 - p + 1) * (1 - rate ** (-value(MPL[r, p, t, v]))) / GDR)
            )

            svars['Costs']['V_DiscountedFixedCostsByProcess', r, t, v] += fcost

        for r, p, t, v in m.CostVariable.sparse_iterkeys():
            if t not in m.tech_annual:
                vcost = sum(
                    value(m.V_FlowOut[r, p, S_s, S_d, S_i, t, v, S_o])
                    for S_i in m.processInputs[r, p, t, v]
                    for S_o in m.ProcessOutputsByInput[r, p, t, v, S_i]
                    for S_s in m.time_season
                    for S_d in m.time_of_day
                )
            else:
                vcost = sum(
                    value(m.V_FlowOutAnnual[r, p, S_i, t, v, S_o])
                    for S_i in m.processInputs[r, p, t, v]
                    for S_o in m.ProcessOutputsByInput[r, p, t, v, S_i]
                )
            if abs(vcost) < epsilon: continue

            vcost *= value(m.CostVariable[r, p, t, v])
            svars['Costs']['V_UndiscountedVariableCostsByProcess', r, t, v] += vcost * value(
                MPL[r, p, t, v])
            vcost *= (
                value(MPL[r, p, t, v]) if not GDR else
                (rate ** (P_0 - p + 1) * (1 - rate ** (-value(MPL[r, p, t, v]))) / GDR)
            )
            svars['Costs']['V_DiscountedVariableCostsByProcess', r, t, v] += vcost

        # update the costs of exchange technologies.
        # Assumption 1: If Ri-Rj appears in the cost tables but Rj-Ri does not,
        # then the total costs are distributed between the regions
        # Ri and Rj proportional to their use of the exchange technology connecting the
        # regions.
        # Assumption 2: If both the directional entries appear in the cost tables,
        # Assumption 1 is no longer applied and the costs are calculated as they
        # are entered in the cost tables.
        # assumption 3: Unlike other output tables in which Ri-Rj and Rj-Ri entries
        # are allowed in the region column, for the Output_Costs table the region
        # to the right of the hyphen sign gets the costs.
        for i in m.RegionalExchangeCapacityConstraint_rrptv:
            reg_dir1 = i[0] + "-" + i[1]
            reg_dir2 = i[1] + "-" + i[0]
            tech = i[3]
            vintage = i[4]
            key = (reg_dir1, tech, vintage)
            try:
                act_dir1 = value(sum(m.V_FlowOut[reg_dir1, p, s, d, S_i, tech, vintage, S_o]
                                     for p in m.time_optimize if
                                     (p < vintage + value(
                                         m.LifetimeProcess[reg_dir1, tech, vintage])) and (
                                             p >= vintage)
                                     for s in m.time_season
                                     for d in m.time_of_day
                                     for S_i in m.processInputs[reg_dir1, p, tech, vintage]
                                     for S_o in
                                     m.ProcessOutputsByInput[reg_dir1, p, tech, vintage, S_i]
                                     ))
                act_dir2 = value(sum(m.V_FlowOut[reg_dir2, p, s, d, S_i, tech, vintage, S_o]
                                     for p in m.time_optimize if
                                     (p < vintage + value(
                                         m.LifetimeProcess[reg_dir1, tech, vintage])) and (
                                             p >= vintage)
                                     for s in m.time_season
                                     for d in m.time_of_day
                                     for S_i in m.processInputs[reg_dir2, p, tech, vintage]
                                     for S_o in
                                     m.ProcessOutputsByInput[reg_dir2, p, tech, vintage, S_i]
                                     ))
            except:
                act_dir1 = value(sum(m.V_FlowOutAnnual[reg_dir1, p, S_i, tech, vintage, S_o]
                                     for p in m.time_optimize if
                                     (p < vintage + value(
                                         m.LifetimeProcess[reg_dir1, tech, vintage])) and (
                                             p >= vintage)
                                     for S_i in m.processInputs[reg_dir1, p, tech, vintage]
                                     for S_o in
                                     m.ProcessOutputsByInput[reg_dir1, p, tech, vintage, S_i]
                                     ))
                act_dir2 = value(sum(m.V_FlowOutAnnual[reg_dir2, p, S_i, tech, vintage, S_o]
                                     for p in m.time_optimize if
                                     (p < vintage + value(
                                         m.LifetimeProcess[reg_dir1, tech, vintage])) and (
                                             p >= vintage)
                                     for S_i in m.processInputs[reg_dir2, p, tech, vintage]
                                     for S_o in
                                     m.ProcessOutputsByInput[reg_dir2, p, tech, vintage, S_i]
                                     ))

            for item in list(svars['Costs']):
                if item[2] == tech:
                    opposite_dir = item[1][item[1].find("-") + 1:] + "-" + item[1][
                                                                           :item[1].find("-")]
                    if (item[0], opposite_dir, item[2], item[3]) in svars['Costs'].keys():
                        continue  # if both directional entries are already in svars[	'Costs'	], they're left intact.
                    if item[1] == reg_dir1:
                        if (act_dir1 + act_dir2) > 0:
                            svars['Costs'][(item[0], reg_dir2, item[2], item[3])] = svars['Costs'][
                                                                                        item] * act_dir2 / (
                                                                                            act_dir1 + act_dir2)
                            svars['Costs'][item] = svars['Costs'][item] * act_dir1 / (
                                    act_dir1 + act_dir2)

        # Remove Ri-Rj entries from being populated in the Outputs_Costs. Ri-Rj means a cost
        # for region Rj
        for item in list(svars['Costs']):
            if item[2] in m.tech_exchange:
                svars['Costs'][(item[0], item[1][item[1].find("-") + 1:], item[2], item[3])] = \
                    svars['Costs'][item]
                del svars['Costs'][item]

    return svars


def stream_results(svars, con_info) -> StringIO:
    """
    process the variables and constraint info into a StringIO object

    Dev Note:  This function and the associated ones needs an overhaul.
    this update merely chops up the big function into bits.
    :param svars:
    :param con_info:
    :return: StringIO object
    """
    output = StringIO()

    # TODO:  This kicks off the output stream.  Come back to it
    # if not myopic_iteration:
    #     msg = ('Model name: %s\n'
    #            'Objective function value (%s): %s\n'
    #            'Non-zero variable values:\n'
    #            )
    #     output.write(msg % (m.name, obj_name, obj_value))

    def make_var_list(variables):
        var_list = []
        for vgroup, values in sorted(variables.items()):
            for vindex, val in sorted(values.items()):
                if isinstance(vindex, tuple):
                    vindex = ','.join(str(i) for i in vindex)
                var_list.append(('{}[{}]'.format(vgroup, vindex), val))
        return var_list

    if svars:
        stringify_data(make_var_list(svars), output)
    else:
        output.write('\nAll variables have a zero (0) value.\n')

    if con_info and len(con_info) > 0:
        output.write('\nBinding constraint values:\n')
        stringify_data(con_info, output)
        del con_info
    else:
        # Since not all Coopr solvers give constraint results, must check
        msg = '\nSelected Coopr solver plugin does not give constraint data.\n'
        output.write(msg)

    output.write('\n\nIf you use these results for a published article, '
                 "please run Temoa with the '--how_to_cite' command line argument for "
                 'citation information.\n')
    return output


def pformat_results(pyomo_instance: 'TemoaModel', results: SolverResults, config: TemoaConfig):
    """
    The main function to initiate the processing of results
    :param pyomo_instance: the solved instance
    :param config: the TemoaConfig object
    :return:
    """
    logger.debug('Starting results processing')

    output = StringIO()
    m = pyomo_instance  # lazy typist

    epsilon = 1e-5  # threshold for "so small it's zero"
    # we want a stricter threshold for printing out capacity values.
    # This is primarily for numerical reasons. In myopic runs, optimal capacities
    # are fed forward into the subsequent myopic solve as existing capacities. If
    # those capacities are very small, then certain equations/inequalities can have
    # very small or very large numbers. This results in a poorly conditioned problem
    # and can lead to numeric instabilities.
    capacity_epsilon = 0.001

    # Gather the variable data...
    myopic_iteration = True if config.scenario_mode == TemoaMode.MYOPIC else False
    svars = gather_variable_data(m, epsilon=epsilon, capacity_epsilon=capacity_epsilon,
                                 myopic_iteration=myopic_iteration)

    # Gather the cost data...
    cost_data = gather_cost_data(m, epsilon=epsilon, myopic_iteration=myopic_iteration)
    # Update the aggregate result
    svars.update(cost_data)

    if config.save_duals:
        soln = results['Solution']
        Cons = soln.Constraint
        con_info, duals = collect_result_data(Cons, epsilon=1e-9, scenario_name=config.scenario)
    else:
        con_info, duals = None, None

    # gather the outputs thus far
    var_stream = stream_results(svars, con_info)
    # concatenate it into the main output stream
    output.write(var_stream.getvalue())

    # -----------------------------------------------------------------
    # Write outputs stored in dictionary to the user-specified database
    # -----------------------------------------------------------------

    # Table dictionary below maps variable names to database table names
    tables = {"V_FlowIn": "Output_VFlow_In", "V_FlowOut": "Output_VFlow_Out",
              "V_Curtailment": "Output_Curtailment", "V_Capacity": "Output_V_Capacity",
              "V_NewCapacity": "Output_V_NewCapacity",
              "V_RetiredCapacity": "Output_V_RetiredCapacity",
              "V_CapacityAvailableByPeriodAndTech": "Output_CapacityByPeriodAndTech",
              "V_EmissionActivityByPeriodAndProcess": "Output_Emissions",
              "Objective": "Output_Objective", "Costs": "Output_Costs"
              }

    db_tables = ['time_periods', 'time_season', 'time_of_day', 'technologies', 'commodities', \
                 'LifetimeTech', 'LifetimeProcess', 'Efficiency', 'EmissionActivity',
                 'ExistingCapacity']

    # TODO:  This logic is carried forward from previous and odd.  Not clear what the run mode
    #        was from before without a config, but it is required now
    if isinstance(config, TemoaConfig):
        if not config.output_database:
            # TODO:  What is intent of below ???
            if config.saveTEXTFILE or config.save_lp_file:
                for inpu in config.dot_dat:
                    print(inpu)
                    file_ty = re.search(r"\b([\w-]+)\.(\w+)\b", inpu)
                new_dir = config.path_to_data + os.sep + file_ty.group(
                    1) + '_' + config.scenario + '_model'
                if os.path.exists(new_dir):
                    rmtree(new_dir)
                os.mkdir(new_dir)
            print("No Output File specified.")
            return output

        con = sqlite3.connect(config.output_database)
        cur = con.cursor()  # A database cursor enables traversal over DB records
        con.text_factory = str  # This ensures data is explored with UTF-8 encoding

        # Copy tables from Input File to DB file.
        # IF output file is empty database.

        cur.execute("SELECT * FROM technologies")
        db_has_inputs = False  # False for empty db file
        for elem in cur:
            db_has_inputs = True  # True for non-empty db file
            break

        # TODO:  This below segment is currently broke, and it isn't clear if it should be revived.  See note below.
        """
        this segment below tries to implement logic around ensuring that the output db file is constructed
        from the same data as the input file, by comparing the filename in a table called input_file that
        may not exist.  As a result, it is possible to inject output into an "other"
        output database.  Even if it were to work, it is a shabby guarantee that the input data is the same
        without a table-by-table comparison, which seems nonsensical
        """
        if db_has_inputs:  # This file could be schema with populated results from previous run. Or it could be a normal db file.

            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='input_file';")
            input_file_table_exists = False
            for i in cur:  # This means that the 'input_file' table exists in db.
                input_file_table_exists = True
            if input_file_table_exists:  # This block distinguishes normal database from schema.
                # This is schema file.
                cur.execute("SELECT file FROM input_file WHERE id is '1';")
                for i in cur:
                    tagged_file = i[0]
                tagged_file = re.sub('["]', "", tagged_file)

                if tagged_file == config.input_file:
                    # If Input_file name matches, add output and check tech/comm
                    dat_to_db(config.input_file, con)
                else:  # the database was not created from the input file...  ??
                    # If not a match, delete output tables and update input_file. Call dat_to_db
                    for i in db_tables:
                        cur.execute("DELETE FROM " + i + ";")
                        cur.execute("VACUUM;")

                    for i in tables.keys():
                        cur.execute("DELETE FROM " + tables[i] + ";")
                        cur.execute("VACUUM;")

                    cur.execute("DELETE FROM input_file WHERE id=1;")
                    cur.execute("INSERT INTO input_file VALUES(1, '" + str(config.input_file) +
                                "');")

                    dat_to_db(i, con)

        else:  # empty schema db file
            cur.execute(
                "CREATE TABLE IF NOT EXISTS input_file ( id integer PRIMARY KEY, file varchar(30));")

            for i in tables.keys():
                cur.execute("DELETE FROM " + tables[i] + ";")
                cur.execute("VACUUM;")

            for i in config.dot_dat:
                cur.execute("DELETE FROM input_file WHERE id=1;")
                cur.execute("INSERT INTO input_file(id, file) VALUES(?, ?);", (1, '"' + i + '"'))
                break
            dat_to_db(i, con)

        # start updating the tables
        for var_name in svars.keys():
            if var_name in tables:
                cur.execute("SELECT DISTINCT scenario FROM '" + tables[var_name] + "'")
                for val in cur:
                    # If scenario exists, delete unless it's a myopic run (for myopic, the scenario results are deleted
                    # before the run in temoa_config.py)
                    if config.scenario == val[0] and config.scenario_mode != TemoaMode.MYOPIC:
                        cur.execute("DELETE FROM " + tables[var_name] + " \
									WHERE scenario is '" + config.scenario + "'")
                if var_name == 'Objective':  # Only associated table without sector info
                    for var_idx in svars[var_name].keys():
                        key_str = str(var_idx)  # only 1 row to write
                        key_str = key_str[1:-1]  # Remove parentheses
                        cur.execute("INSERT INTO " + tables[var_name] + " \
									VALUES('" + config.scenario + "'," + key_str + ", \
									" + str(svars[var_name][var_idx]) + ");")
                else:  # First add 'NULL' for sector then update
                    # Need to loop over keys, which are the index values for the variable 'key'
                    for var_idx in svars[var_name].keys():
                        key_str = str(var_idx)
                        key_str = key_str[1:-1]  # Remove parentheses
                        if var_name != 'Costs':
                            cur.execute("INSERT INTO " + tables[var_name] + \
                                        " VALUES('" + str(var_idx[0]) + "', '" + config.scenario + "','NULL', \
											" + key_str[key_str.find(',') + 1:] + "," + str(
                                svars[var_name][var_idx]) + ");")
                        else:
                            key_str = str((var_idx[0], var_idx[2], var_idx[3]))
                            key_str = key_str[1:-1]  # Remove parentheses
                            cur.execute("INSERT INTO " + tables[var_name] + \
                                        " VALUES('" + str(var_idx[1]) + "', '" + config.scenario + "','NULL', \
										" + key_str + "," + str(svars[var_name][var_idx]) + ");")
                    cur.execute("UPDATE " + tables[var_name] + " SET sector = \
								(SELECT technologies.sector FROM technologies \
								WHERE " + tables[var_name] + ".tech = technologies.tech);")

        # Write the duals...

        # always erase any dual records for this scenario to either (a) start clean or (b) remove stale results

        cur.execute("DELETE FROM main.Output_Duals WHERE main.Output_Duals.scenario = ?", (config.scenario,))
        if config.save_duals:
            if (len(duals) != 0):
                duals.to_sql('Output_Duals', con, if_exists='append')

        con.commit()
        con.close()

        if config.save_excel or config.save_lp_file:
            # TODO:  It isn't clear why we are screening for save_lp_file here ... ?
            if config.save_excel:
                temp_scenario = set()
                temp_scenario.add(config.scenario)
                # make_excel function imported near the top
                excel_filename = config.output_path / config.scenario
                make_excel(str(config.output_database), excel_filename, temp_scenario)

    logger.debug('Finished results processing')
    return output


def dat_to_db(input_file, output_schema, run_partial=False):
    def traverse_dat(dat_filename, search_tablename):

        result_string = ""
        table_found_flag = False

        with open(dat_filename) as f:
            for line in f:
                line = re.sub("[#].*$", " ", line)

                if table_found_flag:
                    result_string += line
                    if re.search(";\s*$", line):
                        break

                if re.search("" + search_tablename + "\s*[:][=]", line):
                    result_string += line
                    table_found_flag = True
                    if re.search(";\s*$", line):
                        break

        return result_string

    #####Code Starts here
    tables_single_value = ['time_exist', 'time_future', 'time_season', 'time_of_day', \
                           'tech_baseload', 'tech_resource', 'tech_production', 'tech_storage', \
                           'commodity_physical', 'commodity_demand', 'commodity_emissions']

    partial_run_tech = ['tech_baseload', 'tech_resource', 'tech_production', 'tech_storage']

    partial_run_comm = ['commodity_physical', 'commodity_demand', 'commodity_emissions']

    tables_multiple_value = ['ExistingCapacity', 'Efficiency', 'LifetimeTech', \
                             'LifetimeProcess', 'EmissionActivity']

    parsed_data = {}

    # if db_or_dat_flag: #This is an input db file
    #	import pdb; pdb.set_trace()
    #	output_schema.execute("ATTACH DATABASE ? AS db2;", "'"+input_file+"'")
    #	for i in db_tables:
    #		output_schema.execute("INSERT INTO "+i+" SELECT * FROM db2."+i+";")

    if run_partial:
        comm_set = set()
        tech_set = set()
        for i in partial_run_comm:
            raw_string = traverse_dat(input_file, i)
            raw_string = re.sub("\s+", " ", raw_string)
            raw_string = re.sub("^.*[:][=]", "", raw_string)
            raw_string = re.sub(";\s*$", "", raw_string)
            raw_string = re.sub("^\s+|\s+$", "", raw_string)
            parsed_data[i] = re.split(" ", raw_string)
            for datas in parsed_data[i]:
                if datas == '':
                    continue
                comm_set.add(datas)

        for i in partial_run_tech:
            raw_string = traverse_dat(input_file, i)
            raw_string = re.sub("\s+", " ", raw_string)
            raw_string = re.sub("^.*[:][=]", "", raw_string)
            raw_string = re.sub(";\s*$", "", raw_string)
            raw_string = re.sub("^\s+|\s+$", "", raw_string)
            parsed_data[i] = re.split(" ", raw_string)
            for datas in parsed_data[i]:
                if datas == '':
                    continue
                tech_set.add(datas)

        return comm_set, tech_set

    # This is an input dat file
    for i in tables_single_value:
        raw_string = traverse_dat(input_file, i)
        raw_string = re.sub("\s+", " ", raw_string)
        raw_string = re.sub("^.*[:][=]", "", raw_string)
        raw_string = re.sub(";\s*$", "", raw_string)
        raw_string = re.sub("^\s+|\s+$", "", raw_string)
        parsed_data[i] = re.split(" ", raw_string)

    for i in tables_multiple_value:
        raw_string = traverse_dat(input_file, i)
        raw_string = re.sub("\n", ",", raw_string)
        raw_string = re.sub("\s+", " ", raw_string)
        raw_string = re.sub("^.*[:][=]\s*,", "", raw_string)
        raw_string = re.sub(",?;\s*,?$", "", raw_string)
        raw_string = re.sub("^\s+|\s+$", "", raw_string)
        raw_string = re.sub("\s?,\s?", ",", raw_string)
        raw_string = re.sub(",+", ",", raw_string)
        parsed_data[i] = re.split(",", raw_string)

    # Fill time_periods
    for i in parsed_data['time_exist']:
        if i == '':
            continue
        output_schema.execute("INSERT OR REPLACE INTO time_periods VALUES(" + i + ", 'e');")
    for i in parsed_data['time_future']:
        if i == '':
            continue
        output_schema.execute("INSERT OR REPLACE INTO time_periods VALUES(" + i + ", 'f');")

    # Fill time_season
    for i in parsed_data['time_season']:
        if i == '':
            continue
        output_schema.execute("INSERT OR REPLACE INTO time_season VALUES('" + i + "');")

    # Fill time_of_day
    for i in parsed_data['time_of_day']:
        if i == '':
            continue
        output_schema.execute("INSERT OR REPLACE INTO time_of_day VALUES('" + i + "');")

    # Fill technologies
    for i in parsed_data['tech_baseload']:
        if i == '':
            continue
        output_schema.execute(
            "INSERT OR REPLACE INTO technologies VALUES('" + i + "', 'pb', '', '');")
    for i in parsed_data['tech_storage']:
        if i == '':
            continue
        output_schema.execute(
            "INSERT OR REPLACE INTO technologies VALUES('" + i + "', 'ph', '', '');")
    for i in parsed_data['tech_production']:
        if i == '':
            continue
        if i in parsed_data['tech_storage']:
            continue
        if i in parsed_data['tech_baseload']:
            continue
        output_schema.execute(
            "INSERT OR REPLACE INTO technologies VALUES('" + i + "', 'p', '', '');")
    for i in parsed_data['tech_resource']:
        if i == '':
            continue
        output_schema.execute(
            "INSERT OR REPLACE INTO technologies VALUES('" + i + "', 'r', '', '');")

    # Fill commodities
    for i in parsed_data['commodity_demand']:
        if i == '':
            continue
        output_schema.execute("INSERT OR REPLACE INTO commodities VALUES('" + i + "', 'd', '');")
    for i in parsed_data['commodity_physical']:
        if i == '':
            continue
        output_schema.execute("INSERT OR REPLACE INTO commodities VALUES('" + i + "', 'p', '');")
    for i in parsed_data['commodity_emissions']:
        if i == '':
            continue
        output_schema.execute("INSERT OR REPLACE INTO commodities VALUES('" + i + "', 'e', '');")

    # Fill ExistingCapacity
    for i in parsed_data['ExistingCapacity']:
        if i == '':
            continue
        row_data = re.split(" ", i)
        row_data.append('')
        row_data.append('')
        output_schema.execute("INSERT OR REPLACE INTO ExistingCapacity VALUES(?, ?, ?, ?, ?);",
                              row_data)

    # Fill Efficiency
    for i in parsed_data['Efficiency']:
        if i == '':
            continue
        row_data = re.split(" ", i)
        row_data.append('')
        output_schema.execute("INSERT OR REPLACE INTO Efficiency VALUES(?, ?, ?, ?, ?, ?);",
                              row_data)

    # Fill LifetimeTech
    for i in parsed_data['LifetimeTech']:
        if i == '':
            continue
        row_data = re.split(" ", i)
        row_data.append('')
        output_schema.execute("INSERT OR REPLACE INTO LifetimeTech VALUES(?, ?, ?);", row_data)

    # Fill LifetimeProcess
    for i in parsed_data['LifetimeProcess']:
        if i == '':
            continue
        row_data = re.split(" ", i)
        row_data.append('')
        output_schema.execute("INSERT OR REPLACE INTO LifetimeProcess VALUES(?, ?, ?, ?);",
                              row_data)

    # Fill EmissionActivity
    for i in parsed_data['EmissionActivity']:
        if i == '':
            continue
        row_data = re.split(" ", i)
        row_data.append('')
        if len(row_data) == 7:
            row_data.append('')
        output_schema.execute(
            "INSERT OR REPLACE INTO EmissionActivity VALUES(?, ?, ?, ?, ?, ?, ?, ?);", row_data)
