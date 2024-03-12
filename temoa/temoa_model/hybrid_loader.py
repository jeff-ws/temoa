"""
A module to build/load a Data Portal for myopic run using both SQL to pull data
and python to filter results
"""
import time
from collections import defaultdict
from logging import getLogger
from sqlite3 import Connection, OperationalError
from typing import Sequence

import deprecated
from pyomo.core import Param, Set
from pyomo.dataportal import DataPortal

from temoa.extensions.myopic.myopic_index import MyopicIndex
from temoa.temoa_model.model_checking import network_model_data
from temoa.temoa_model.model_checking.commodity_network import CommodityNetwork
from temoa.temoa_model.temoa_config import TemoaConfig
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
Created on:  1/21/24

"""

logger = getLogger(__name__)

# the tables below are ones in which we might find regional groups which should be captured
# to make the members of the RegionalGlobalIndices Set in the model.  They need to aggregated
tables_with_regional_groups = {
    'MaxActivity': 'regions',
    'MinActivity': 'regions',
    'MinAnnualCapacityFactor': 'regions',
    'MaxAnnualCapacityFactor': 'regions',
    'EmissionLimit': 'regions',
    'MinActivityGroup': 'regions',
    'MaxActivityGroup': 'regions',
    'MinCapacityGroup': 'regions',
    'MaxCapacityGroup': 'regions',
}


class HybridLoader:
    """
    An instance of the HybridLoader
    """

    def __init__(self, db_connection: Connection, config: TemoaConfig):
        self.debugging = False  # for T/S, will print to screen the data load values
        self.con = db_connection
        self.config = config

        # filters for myopic ops
        self.viable_techs: set[str] = set()
        self.viable_comms: set[str] = set()
        self.viable_input_comms: set[str] = set()
        self.viable_output_comms: set[str] = set()
        self.viable_vintages: set[int] = set()
        self.viable_rtv: set[tuple[str, str, int]] = set()
        self.viable_rt: set[tuple[str, str]] = set()
        self.efficiency_values: list[tuple] = []

    def _build_eff_table(self, myopic_index: MyopicIndex | None):
        """Build efficiency data by using the source_check functionality on the data
        to analyze the network and deterimine good/bad techs before loading anything else.  Use this to
        load the filters..."""
        cur = self.con.cursor()
        self._clear_filters()
        network_data = network_model_data.build(self.con)

        # need regions and periods to execute the source check by [r, p].  At this point, we can only pull from DB
        regions = {region for region, _ in cur.execute('SELECT regions FROM regions').fetchall()}
        periods = {period for period, _ in cur.execute("SELECT t_periods FROM time_periods WHERE flag = 'f'")}
        good_tech = set()
        # we need to work through all region-period pairs and:
        # (1) run the source trace
        # (2) pull the "good connections" (techs) out and add them to efficiency data
        # (3) make a plot, if requested
        # (4) log the orphans
        for region in regions:
            for period in periods:
                network = CommodityNetwork(region=region, period=period, model_data=network_data)
                network.analyze_network()
                good_tech.update(network.get_valid_tech())
                if self.config and self.config.plot_commodity_network:
                    network.graph_network(self.config)

                for tech in network.get_demand_side_orphans():
                    logger.warning('tech %s is a demand-side orphan and has been removed', tech)
                for tech in network.get_other_orphans():
                    logger.warning('tech %s is an "other orphan" and has been removed', tech)

        # pull the elements "for real" and filter them...

        contents = cur.execute(
            'SELECT region, input_comm, tech, vintage, output_comm, efficiency, lifetime  '
            'FROM MyopicEfficiency '
            'WHERE vintage + lifetime > ?',
            (myopic_index.base_year,),
            ).fetchall()
        logger.debug('polled %d elements from MyopicEfficiency table', len(contents))
        efficiency_entries = {
            (r, i, t, v, o, eff, lifetime) for r, i, t, v, o, eff, lifetime in contents
        }
    def _build_myopic_eff_table(self, myopic_index: MyopicIndex):
        """
        refresh all the sets used for filtering from the current contents
        of the MyopicEfficiency table.  This should normally be called
        after a Myopic iteration where MyopicEfficiency is updated
        :return:
        """
        cur = self.con.cursor()
        self._clear_filters()
        # the sequencer is responsible for updating the MyopicEfficiency table, so we should
        # just be able to pull directly from it for things that are alive as of the base year
        contents = cur.execute(
            'SELECT region, input_comm, tech, vintage, output_comm, efficiency, lifetime  '
            'FROM MyopicEfficiency '
            'WHERE vintage + lifetime > ?',
            (myopic_index.base_year,),
        ).fetchall()
        logger.debug('polled %d elements from MyopicEfficiency table', len(contents))

        # We will need to ID the physical commodities for later filtering...
        raw = cur.execute(
            "SELECT comm_name FROM main.commodities WHERE flag = 'p' OR flag = 's'"
        ).fetchall()
        phys_commodities = {t[0] for t in raw}
        assert len(phys_commodities) > 0, 'Failsafe...we should find some!  Did flag change?'

        # We will need to iterate a bit here to:
        # 1.  Screen all the input commodities to identify "viable" commodities
        # 2.  Find any tech with PHYSICAL output commodity that is not in set of viable commodities
        # 3.  Suppress that tech
        # 4.  re-screen the input commodities
        # 5.  quit when no more techs are suppressed
        # 6.  publish viable commodities & viable techs

        # we probably need to keep track of (r, t, v) tuples here because you *could*
        # have a tech process different things in different vintages/regions based solely
        # on differences in Efficiency Table

        techs_by_production_output = defaultdict(set)  # {phys_output_comm: { techs } }
        ok_techs = set()
        existing_techs = set()
        suppressed_techs = set()
        input_commodities = set()
        for r, c1, t, v, c2, eff, lifetime in contents:
            row = (r, c1, t, v, c2, eff)
            if c1 not in phys_commodities:
                raise ValueError(f'Tech {t} has a non-physical input: {c1}')
            input_commodities.add(c1)
            # TODO:  think of alternatives here....
            # we will add any already built (existing capacity) techs to "OK techs" because they are de-facto
            # already in existence.  This *might* cause a model warning regarding unused outputs if there is no
            # longer a receiver for their output.

            # CHANGE HERE.  It is actually possible for an earlier vintage tech to be invalid/problematic
            # if it produces an output that is not wanted by anything (all possible receivers have been
            # suppressed).  In that case, the build will crash because the output commodity from that
            # tech will not be in the legal physical commodities.  So, we do need to screen them too.
            # will leave the code in case another alternative is discovered.

            # if v < myopic_index.base_year:
            #     existing_techs.add(row)

            ok_techs.add(row)
            # we screen here to not worry about demand/emission outputs
            if c2 in phys_commodities:
                techs_by_production_output[c2].add(row)

        # identify the "illegal" outputs as any output that is not in demand by something else or a demand commodity
        # itself
        illegal_outputs = set(techs_by_production_output.keys()) - input_commodities

        # we want to exclude any existing techs from this screening...  they should persist, even if no value ATT.
        # removing them from ok_techs will give them a free pass and  enable the loop below to complete
        ok_techs -= existing_techs
        # this needs to be done iteratively because pulling 1 tech *might* make an output from another tech
        # illegal
        iter_count = 0
        while illegal_outputs:
            for output in illegal_outputs:
                # mark all the techs that push that output as "suppressed", UNLESS they are existing capacity techs
                # this should effectively suppress any NEW techs in this window, but still allow legacy/existing ones
                # through
                suppressed_techs.update(techs_by_production_output[output])
            # remove from viable
            ok_techs -= suppressed_techs
            # re-capture tech by output
            techs_by_production_output.clear()
            for row in ok_techs:
                r, c1, t, v, c2, eff = row
                if c2 in phys_commodities:
                    techs_by_production_output[c2].add(row)

            # re-screen for a new list of viable commodities from inputs
            input_commodities = {row[1] for row in ok_techs}
            illegal_outputs = set(techs_by_production_output.keys()) - input_commodities
            iter_count += 1
            if iter_count % 10 == 0:
                print(f'Iteration {iter_count}, suppressed techs: {len(suppressed_techs)}')

        # log the deltas
        if suppressed_techs:
            logger.debug('Reduced techs in Efficiency from %d to %d', len(contents), len(ok_techs))
            for tech in suppressed_techs:
                logger.info(
                    'Tech: %s\n'
                    ' is SUPPRESSED as it has a Physical Commodity output that has no viable '
                    'receiver',
                    tech,
                )
        if len(input_commodities) < len(raw):
            logger.debug(
                'Reduced Input (Physical/Supply) Commodities from %d to %d by '
                'dropping unused commodities: %s',
                len(phys_commodities),
                len(input_commodities),
                phys_commodities - input_commodities,
            )

        # now, we want to use the existing techs unioned with the screened new techs to form our filter basis
        for row in ok_techs | existing_techs:
            r, c1, t, v, c2, _ = row
            self.viable_techs.add(t)
            self.viable_input_comms.add(c1)
            self.viable_rtv.add((r, t, v))
            self.viable_vintages.add(v)
            self.viable_output_comms.add(c2)
        self.viable_rt = {(r, t) for r, t, v in self.viable_rtv}
        self.viable_comms = self.viable_input_comms | self.viable_output_comms

        # book the EfficiencyTable
        # we should sort here for deterministic results after pulling from set
        self.efficiency_values = sorted(ok_techs | existing_techs)

    def _build_eff_table(self):
        """
        Build the Efficiency Table data without regard for filtering that is done with the myopic build.  This is
        intended for use in Perfect Foresight and other modes.
        :return:
        """
        cur = self.con.cursor()
        self._clear_filters()  # needed?

        contents = cur.execute(
            'SELECT regions, input_comm, tech, vintage, output_comm, efficiency FROM main.Efficiency'
        ).fetchall()
        logger.debug('polled %d rows from Efficiency table data', len(contents))
        self.efficiency_values = [row[0] for row in contents]

    def _clear_filters(self):
        self.viable_techs.clear()
        self.viable_input_comms.clear()
        self.viable_output_comms.clear()
        self.viable_comms.clear()
        self.viable_rtv.clear()
        self.viable_rt.clear()
        self.viable_vintages.clear()
        self.efficiency_values.clear()

    def table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists in the schema... for use with "optional" tables
        :param table_name: the table name to check
        :return: True if it exists in the schema
        """
        table_name_check = (
            self.con.cursor()
            .execute("SELECT name FROM sqlite_master WHERE type='table' AND name= ?", (table_name,))
            .fetchone()
        )
        if table_name_check:
            return True
        logger.info('Did not find existing table for (optional) table:  %s', table_name)
        return False

    @staticmethod
    @deprecated.deprecated('no longer needed')
    def _efficiency_table_cleanup(
        raw_data: list[tuple], physical_commodities: Sequence
    ) -> list[tuple]:
        """
        A cleanup for the data going in to the efficiency table.  Needed to ensure that there
        are no cases where a commodity can be an input before it is available as an output
        or vice-versa.  Filtering only occurs after the base year passed in, so anything
        "existing" is ignored
        :param raw_data: the query result
        :param physical_commodities: the first year to apply the filtering on
        :return: filtered data set for Efficiency, reduced list of physical commodities
        """

        if len(physical_commodities) == 0:
            raise ValueError('No production commodities provided to efficiency filter')
        if not isinstance(physical_commodities, set):
            physical_commodities = set(physical_commodities)

        visible_inputs = {
            input_comm for region, input_comm, tech, vintage, output_comm, efficiency in raw_data
        }
        visible_outputs = {
            output_comm for region, input_comm, tech, vintage, output_comm, efficiency in raw_data
        }

        filtered_data = []
        for row in raw_data:
            region, input_comm, tech, vintage, output_comm, efficiency = row
            if output_comm in physical_commodities and output_comm not in visible_inputs:
                logger.warning(
                    'For Efficiency table entry: \n'
                    '    %s\n'
                    '    There are no sources to accept the physical commodity output: '
                    '%s\n'
                    '    Either the commodity is mislabeled as physical or this tech is '
                    'ahead of need.  This Efficiency entry is SUPPRESSED.',
                    row,
                    output_comm,
                )
            else:
                filtered_data.append(row)
            if input_comm not in visible_outputs:
                logger.warning(
                    'For Efficiency table entry: \n'
                    '    %s\n'
                    '    There are no sources to supply the input commodity: '
                    '%s\n'
                    '    Advisory only, no action taken.',
                    row,
                    input_comm,
                )

        return filtered_data

    def load_data_portal(self, myopic_index: MyopicIndex | None = None) -> DataPortal:
        # the general plan:
        # 1. iterate through the model elements that are directly read from data
        # 2. use SQL query to get the full table
        # 3. (OPTIONALLY) filter it, as needed for myopic
        # 4. load it into the data dictionary
        tic = time.time()

        if myopic_index is not None and not isinstance(myopic_index, MyopicIndex):
            raise ValueError(f'received an illegal entry for the myopic index: {myopic_index}')
        elif myopic_index:
            mi = myopic_index  # abbreviated name
            self._build_myopic_eff_table(myopic_index=mi)
        else:
            mi = None
            self._build_eff_table()

        # housekeeping
        data: dict[str, list | dict] = dict()

        def load_element(
            c: Set | Param,
            values: Sequence[tuple],
            validation: set | None = None,
            val_loc: tuple = None,
        ):
            """
            Helper to alleviate some typing!
            Expects that the values passed in are an iterable of tuples, like a standard
            query result.  Note that any filtering is disregarded if there is no myopic index in use
            :param c: the model component to load
            :param values: the keys for param or the item values for set as tuples
            :param validation: the set to validate the keys/set value against
            :param val_loc: tuple of the positions of r, t, v in the key for validation
            :return: None
            """
            if len(values) == 0:
                logger.info('table, but no (usable) values for param or set: %s', c.name)
                return
            if not isinstance(values[0], tuple):
                raise ValueError('values must be an iterable of tuples')

            match c:
                case Set():  # it is a pyomo Set
                    # note:  we will put the set values into lists to establish order.  Passing a set into
                    #        pyomo as an initializer will raise a warning about initializing from non-ordered...

                    # check for multi-dim sets
                    if len(values) > 0 and len(values[0]) > 1:  # this contains multi-dim values
                        if validation and mi:
                            if not val_loc:
                                raise ValueError(
                                    'Trying to use a validation but missing location field in call.'
                                )
                            if validation is self.viable_rtv:
                                data[c.name] = [
                                    t
                                    for t in values
                                    if (t[val_loc[0]], t[val_loc[1]], t[val_loc[2]])
                                    in self.viable_rtv
                                ]
                            if validation is self.viable_rt:
                                data[c.name] = [
                                    t
                                    for t in values
                                    if (t[val_loc[0]], t[val_loc[1]]) in self.viable_rt
                                ]
                            if validation is self.viable_vintages:
                                data[c.name] = [
                                    t for t in values if t[val_loc[0]] in self.viable_vintages
                                ]
                        else:
                            data[c.name] = [t for t in values]

                    elif validation and mi:
                        data[c.name] = [t[0] for t in values if t[0] in validation]
                    else:
                        data[c.name] = [t[0] for t in values]
                case Param():  # c is a pyomo Param
                    if validation and mi:
                        if validation is self.viable_rtv:
                            if not val_loc:
                                raise ValueError(
                                    'Trying to validate against r, t, v and got no locations'
                                )
                            data[c.name] = {
                                t[:-1]: t[-1]
                                for t in values
                                if (t[val_loc[0]], t[val_loc[1]], t[val_loc[2]]) in self.viable_rtv
                            }
                            # quick check for region-groups which shouldn't show up here...
                            regions_screened = {t[val_loc[0]] for t in values}
                            groups_discovered = {t for t in regions_screened if '+' in t}
                            if len(groups_discovered) > 0:
                                logger.error(
                                    'Region-Groups discovered during screen of:  %s.'
                                    'likely error in loader / param description.',
                                    c.name,
                                )
                        elif validation is self.viable_rt:
                            if not val_loc:
                                raise ValueError(
                                    'Trying to validate against r, t and got no locations'
                                )
                            data[c.name] = {
                                t[:-1]: t[-1]
                                for t in values
                                if (t[val_loc[0]], t[val_loc[1]]) in self.viable_rt
                            }
                        else:
                            if val_loc:
                                data[c.name] = {
                                    t[:-1]: t[-1] for t in values if t[val_loc[0]] in validation
                                }
                            else:
                                data[c.name] = {
                                    t[:-1]: t[-1] for t in values if t[:-1] in validation
                                }
                    else:
                        data[c.name] = {t[:-1]: t[-1] for t in values}
                case _:
                    raise ValueError(f'Component type unrecognized: {c}, {type(c)}')

        M: TemoaModel = TemoaModel()  # for typing purposes only
        cur = self.con.cursor()

        #   === TIME SETS ===

        # time_exist
        if mi:
            raw = cur.execute(
                'SELECT t_periods FROM main.time_periods WHERE t_periods < ?', (mi.base_year,)
            ).fetchall()
        else:
            raw = cur.execute("SELECT t_periods FROM main.time_periods WHERE flag = 'e'").fetchall()
        load_element(M.time_exist, raw)

        # time_future
        if mi:
            raw = cur.execute(
                'SELECT t_periods FROM main.time_periods WHERE '
                't_periods >= ? AND t_periods <= ?',
                (mi.base_year, mi.last_year),
            ).fetchall()
        else:
            raw = cur.execute("SELECT t_periods FROM main.time_periods WHERE flag = 'f'").fetchall()
        load_element(M.time_future, raw)

        # time_of_day
        raw = cur.execute('SELECT t_day FROM main.time_of_day').fetchall()
        load_element(M.time_of_day, raw)

        # time_season
        raw = cur.execute('SELECT t_season FROM main.time_season').fetchall()
        load_element(M.time_season, raw)

        # myopic_base_year
        if mi and self.table_exists('MyopicBaseyear'):
            raw = cur.execute('SELECT year from main.MyopicBaseyear').fetchall()
            # load as a singleton...
            if not raw:
                raise ValueError('No "year" found in MyopicBaseyear table.')
            data[M.MyopicBaseyear.name] = {None: int(raw[0][0])}
        elif mi:
            raise ValueError('Running in myopic mode is not possible without MyopicBaseyear table.')

        #  === REGION SETS ===

        # regions
        raw = cur.execute('SELECT regions FROM main.regions').fetchall()
        load_element(M.regions, raw)

        # region-groups  (these are the R1+R2, R1+R4+R6 type region labels)
        regions_and_groups = set()
        for table, field_name in tables_with_regional_groups.items():
            if self.table_exists(table):
                raw = cur.execute(f'SELECT {field_name} from main.{table}').fetchall()
                regions_and_groups.update({t[0] for t in raw})
        # filter to those that contain "+" and sort (for deterministic pyomo behavior)
        # TODO:  RN, this set contains all regular regions, inteconnects, AND groups, so we don't filter ... yet
        list_of_groups = sorted((t,) for t in regions_and_groups)  # if "+" in t or t=='global')
        load_element(M.RegionalGlobalIndices, list_of_groups)

        # region-exchanges
        # TODO:  Perhaps tease the exchanges out of the efficiency table...?  RN, they are all auto-generated.

        #  === TECH SETS ===

        # tech_resource
        raw = cur.execute("SELECT tech FROM main.technologies WHERE flag = 'r'").fetchall()
        load_element(M.tech_resource, raw, self.viable_techs)

        # tech_production
        raw = cur.execute("SELECT tech FROM main.technologies WHERE flag LIKE 'p%'").fetchall()
        load_element(M.tech_production, raw, self.viable_techs)

        # tech_uncap
        try:
            raw = cur.execute('SELECT tech FROM main.technologies WHERE unlim_cap > 0').fetchall()
            load_element(M.tech_uncap, raw, self.viable_techs)
        except OperationalError:
            logger.info(
                'The current database does not support non-capacity techs and should be upgraded.'
            )

        # tech_baseload
        raw = cur.execute("SELECT tech FROM main.technologies WHERE flag = 'pb'").fetchall()
        load_element(M.tech_baseload, raw, self.viable_techs)

        # tech_storage
        raw = cur.execute("SELECT tech FROM main.technologies WHERE flag = 'ps'").fetchall()
        load_element(M.tech_storage, raw, self.viable_techs)

        # tech_reserve
        raw = cur.execute('SELECT tech FROM main.tech_reserve').fetchall()
        load_element(M.tech_reserve, raw, self.viable_techs)

        # tech_ramping
        techs = set()
        if self.table_exists('RampUp'):
            ramp_up_techs = cur.execute('SELECT tech FROM main.RampUp').fetchall()
            techs.update({t[0] for t in ramp_up_techs})
        if self.table_exists('RampDown'):
            ramp_dn_techs = cur.execute('SELECT tech FROM main.RampDown').fetchall()
            techs.update({t[0] for t in ramp_dn_techs})
        load_element(M.tech_ramping, sorted((t,) for t in techs), self.viable_techs)  # sort for
        # deterministic behavior

        # tech_reserve
        raw = cur.execute('SELECT tech FROM main.tech_reserve').fetchall()
        load_element(M.tech_reserve, raw, self.viable_techs)

        # tech_curtailment
        raw = cur.execute('SELECT tech FROM main.tech_curtailment').fetchall()
        load_element(M.tech_curtailment, raw, self.viable_techs)

        # tech_rps
        if self.table_exists('tech_rps'):
            raw = cur.execute('SELECT region, tech FROM main.tech_rps').fetchall()
            load_element(M.tech_rps, raw, self.viable_rt, (0, 1))

        # tech_flex
        raw = cur.execute('SELECT tech FROM main.tech_flex').fetchall()
        load_element(M.tech_flex, raw, self.viable_techs)

        # tech_exchange
        raw = cur.execute('SELECT tech FROM main.tech_exchange').fetchall()
        load_element(M.tech_exchange, raw, self.viable_techs)

        # groups & tech_groups (supports RPS)
        if self.table_exists('groups'):
            raw = cur.execute('SELECT group_name FROM main.groups').fetchall()
            load_element(M.groups, raw)

        if self.table_exists('tech_groups'):
            raw = cur.execute('SELECT region, group_name, tech FROM main.tech_groups').fetchall()
            load_element(M.tech_groups, raw, self.viable_rt, (0, 2))

        # tech_annual
        raw = cur.execute('SELECT tech FROM main.tech_annual').fetchall()
        load_element(M.tech_annual, raw, self.viable_techs)

        # tech_variable
        if self.table_exists('tech_variable'):
            raw = cur.execute('SELECT tech FROM main.tech_variable').fetchall()
            load_element(M.tech_variable, raw, self.viable_techs)

        # tech_retirement
        if self.table_exists('tech_retirement'):
            raw = cur.execute('SELECT tech FROM main.tech_retirement').fetchall()
            load_element(M.tech_retirement, raw, self.viable_techs)

        #  === COMMODITIES ===

        # commodity_demand
        raw = cur.execute("SELECT comm_name FROM main.commodities WHERE flag = 'd'").fetchall()
        load_element(M.commodity_demand, raw, self.viable_comms)

        # commodity_emissions
        # currently NOT validated against anything... shouldn't be a problem ?
        raw = cur.execute("SELECT comm_name FROM main.commodities WHERE flag = 'e'").fetchall()
        load_element(M.commodity_emissions, raw)

        # commodity_physical
        raw = cur.execute(
            "SELECT comm_name FROM main.commodities WHERE flag = 'p' OR flag = 's'"
        ).fetchall()
        # The model enforces 0 symmetric difference between the physical commodities
        # and the input commodities, so we need to include only the viable INPUTS
        load_element(M.commodity_physical, raw, self.viable_input_comms)

        # commodity_source
        raw = cur.execute("SELECT comm_name FROM main.commodities WHERE flag = 's'").fetchall()
        load_element(M.commodity_source, raw, self.viable_input_comms)

        #  === PARAMS ===

        # Efficiency
        if mi:
            # use what we have already computed
            raw = self.efficiency_values
        else:
            raw = cur.execute(
                'SELECT regions, input_comm, tech, vintage, output_comm, efficiency '
                'FROM main.Efficiency',
            ).fetchall()

        load_element(M.Efficiency, raw)

        # ExistingCapacity
        if mi:
            # In order to get accurate capacity at start of this interval, we want to
            # 1.  Only look at the previous period in the net capacity table (things that had some capacity)
            # 2.  Omit any techs that are "unlimited capacity" to keep them out of capacity variables
            # 3.  add in everything from the original ExistingCapacity table

            # get previous period
            raw = cur.execute(
                'SELECT MAX(t_periods) FROM main.time_periods WHERE t_periods < ?', (mi.base_year,)
            ).fetchone()
            previous_period = raw[0]
            # noinspection SqlUnused
            raw = cur.execute(
                'SELECT region, tech, vintage, capacity FROM main.MyopicNetCapacity '
                ' WHERE period = ? '
                '  AND tech NOT IN (SELECT tech FROM main.technologies WHERE technologies.unlim_cap > 0)'
                'UNION '
                '  SELECT regions, tech, vintage, exist_cap FROM main.ExistingCapacity ',
                (previous_period,),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT regions, tech, vintage, exist_cap FROM main.ExistingCapacity'
            ).fetchall()
        load_element(M.ExistingCapacity, raw, self.viable_rtv, (0, 1, 2))

        # GlobalDiscountRate
        raw = cur.execute('SELECT rate FROM main.GlobalDiscountRate').fetchall()
        # do this separately as it is non-indexed, so we need to make a mapping with None
        data[M.GlobalDiscountRate.name] = {None: raw[0][0]}

        # SegFrac
        raw = cur.execute(
            'SELECT season_name, time_of_day_name, segfrac FROM main.SegFrac'
        ).fetchall()
        load_element(M.SegFrac, raw)

        # DemandSpecificDistribution
        raw = cur.execute(
            'SELECT regions, season_name, time_of_day_name, demand_name, dds FROM main.DemandSpecificDistribution'
        ).fetchall()
        load_element(M.DemandSpecificDistribution, raw)

        # Demand
        if mi:
            raw = cur.execute(
                'SELECT regions, periods, demand_comm, demand FROM main.Demand '
                'WHERE periods >= ? AND periods <= ?',
                (mi.base_year, mi.last_demand_year),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT regions, periods, demand_comm, demand FROM main.Demand '
            ).fetchall()
        load_element(M.Demand, raw)

        # RescourceBound
        # TODO:  later, it isn't used RN anyhow.

        # CapacityToActivity
        raw = cur.execute('SELECT regions, tech, c2a FROM main.CapacityToActivity ').fetchall()
        load_element(M.CapacityToActivity, raw, self.viable_rt, (0, 1))

        # CapacityFactorTech
        raw = cur.execute(
            'SELECT regions, season_name, time_of_day_name, tech, cf_tech '
            'FROM main.CapacityFactorTech'
        ).fetchall()
        load_element(M.CapacityFactorTech, raw, self.viable_rt, (0, 3))

        # CapacityFactorProcess
        raw = cur.execute(
            'SELECT regions, season_name, time_of_day_name, tech, vintage, cf_process '
            ' FROM main.CapacityFactorProcess'
        ).fetchall()
        load_element(M.CapacityFactorProcess, raw, self.viable_rtv, (0, 3, 4))

        # LifetimeTech
        raw = cur.execute('SELECT regions, tech, life FROM main.LifetimeTech').fetchall()
        load_element(M.LifetimeTech, raw, self.viable_rt, val_loc=(0, 1))

        # LifetimeProcess
        raw = cur.execute(
            'SELECT regions, tech, vintage, life_process FROM main.LifetimeProcess'
        ).fetchall()
        load_element(M.LifetimeProcess, raw, self.viable_rtv, val_loc=(0, 1, 2))

        # LifetimeLoanTech
        raw = cur.execute('SELECT regions, tech, loan FROM main.LifetimeLoanTech').fetchall()
        load_element(M.LifetimeLoanTech, raw, self.viable_rt, (0, 1))

        # TechInputSplit
        if mi:
            raw = cur.execute(
                'SELECT regions, periods, input_comm, tech, ti_split FROM main.TechInputSplit '
                'WHERE periods >= ? AND periods <= ?',
                (mi.base_year, mi.last_demand_year),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT regions, periods, input_comm, tech, ti_split FROM main.TechInputSplit '
            ).fetchall()
        load_element(M.TechInputSplit, raw, self.viable_rt, (0, 3))

        # TechInputSplitAverage
        if self.table_exists('TechInputSplitAverage'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, input_comm, tech, ti_split '
                    'FROM main.TechInputSplitAverage '
                    'WHERE periods >= ? AND periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, input_comm, tech, ti_split '
                    'FROM main.TechInputSplitAverage '
                ).fetchall()
            load_element(M.TechInputSplitAverage, raw, self.viable_rt, (0, 3))

        # TechOutputSplit
        if self.table_exists('TechOutputSplit'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, tech, output_comm, to_split FROM main.TechOutputSplit '
                    'WHERE periods >= ? AND periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, tech, output_comm, to_split FROM main.TechOutputSplit '
                ).fetchall()
            load_element(M.TechOutputSplit, raw, self.viable_rt, (0, 2))

        # RenewablePortfolioStandard
        if self.table_exists('RenewablePortfolioStandard'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, rps FROM main.RenewablePortfolioStandard '
                    ' WHERE periods >= ? AND periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, rps FROM main.RenewablePortfolioStandard '
                ).fetchall()
            load_element(M.RenewablePortfolioStandard, raw)

        # CostFixed
        if mi:
            raw = cur.execute(
                'SELECT regions, periods, tech, vintage, cost_fixed FROM main.CostFixed '
                'WHERE periods >= ? AND periods <= ?',
                (mi.base_year, mi.last_demand_year),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT regions, periods, tech, vintage, cost_fixed FROM main.CostFixed '
            ).fetchall()
        load_element(M.CostFixed, raw, self.viable_rtv, val_loc=(0, 2, 3))

        # CostInvest
        # exclude "existing" vintages by screening for base year and beyond.
        # the "viable_rtv" will filter anything beyond view
        if mi:
            raw = cur.execute(
                'SELECT regions, tech, vintage, cost_invest FROM main.CostInvest '
                'WHERE vintage >= ?',
                (mi.base_year,),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT regions, tech, vintage, cost_invest FROM main.CostInvest '
            ).fetchall()
        load_element(M.CostInvest, raw, self.viable_rtv, (0, 1, 2))

        # CostVariable
        if mi:
            raw = cur.execute(
                'SELECT regions, periods, tech, vintage, cost_variable FROM main.CostVariable '
                'WHERE periods >= ? AND periods <= ?',
                (mi.base_year, mi.last_demand_year),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT regions, periods, tech, vintage, cost_variable FROM main.CostVariable '
            ).fetchall()
        load_element(M.CostVariable, raw, self.viable_rtv, (0, 2, 3))

        # DiscountRate
        if mi:
            raw = cur.execute(
                'SELECT regions, tech, vintage, tech_rate FROM main.DiscountRate '
                'WHERE vintage >= ?',
                (mi.base_year,),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT regions, tech, vintage, tech_rate FROM main.DiscountRate '
            ).fetchall()

        load_element(M.DiscountRate, raw, self.viable_rtv, (0, 1, 2))

        # MinCapacity
        if self.table_exists('MinCapacity'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, tech, mincap FROM main.MinCapacity '
                    'WHERE periods >= ? AND periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, tech, mincap FROM main.MinCapacity '
                ).fetchall()
            load_element(M.MinCapacity, raw, self.viable_rt, (0, 2))

        # MaxCapacity
        if self.table_exists('MaxCapacity'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, tech, maxcap FROM main.MaxCapacity '
                    'WHERE periods >= ? AND periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, tech, maxcap FROM main.MaxCapacity '
                ).fetchall()
            load_element(M.MaxCapacity, raw, self.viable_rt, (0, 2))

        # MinNewCap
        if self.table_exists('MinNewCapacity'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, tech, mincap FROM main.MinNewCapacity '
                    'WHERE periods >= ? AND periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, tech, mincap FROM main.MinNewCapacity '
                ).fetchall()
            load_element(M.MinNewCapacity, raw, self.viable_rt, (0, 2))

        # MaxNewCap
        if self.table_exists('MaxNewCapacity'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, tech, maxcap FROM main.MaxNewCapacity '
                    'WHERE periods >= ? AND periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, tech, maxcap FROM main.MaxNewCapacity '
                ).fetchall()
            load_element(M.MaxNewCapacity, raw, self.viable_rt, (0, 2))

        # MaxCapacityGroup
        if self.table_exists('MaxCapacityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, t_periods, group_name, max_cap_g FROM main.MaxCapacityGroup '
                    ' WHERE t_periods >= ? AND t_periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, t_periods, group_name, max_cap_g FROM main.MaxCapacityGroup '
                ).fetchall()
            load_element(M.MaxCapacityGroup, raw)

        # MinCapacityGroup
        if self.table_exists('MinCapacityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, t_periods, group_name, min_cap_g FROM main.MinCapacityGroup '
                    ' WHERE t_periods >= ? AND t_periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, t_periods, group_name, min_cap_g FROM main.MinCapacityGroup '
                ).fetchall()
            load_element(M.MinCapacityGroup, raw)

        # MinNewCapacityGroup
        if self.table_exists('MinNewCapacityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, group_name, minnewcap FROM main.MinNewCapacityGroup '
                    ' WHERE t_periods >= ? AND t_periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, group_name, minnewcap FROM main.MinNewCapacityGroup '
                ).fetchall()
            load_element(M.MinNewCapacityGroup, raw)

        # MaxNewCapacityGroup
        if self.table_exists('MaxNewCapacityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, group_name, maxnewcap FROM main.MaxNewCapacityGroup '
                    ' WHERE t_periods >= ? AND t_periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, group_name, maxnewcap FROM main.MaxNewCapacityGroup '
                ).fetchall()
            load_element(M.MaxNewCapacityGroup, raw)

        # MinCapacityShare
        if self.table_exists('MinCapacityShare'):
            raw = cur.execute(
                'SELECT regions, periods, tech, group_name, mincapshare FROM main.MinCapacityShare'
            ).fetchall()
            load_element(M.MinCapacityShare, raw, self.viable_rt, (0, 2))

        # MaxCapacityShare
        if self.table_exists('MaxCapacityShare'):
            raw = cur.execute(
                'SELECT regions, periods, tech, group_name, maxcapshare FROM main.MaxCapacityShare'
            ).fetchall()
            load_element(M.MaxCapacityShare, raw, self.viable_rt, (0, 2))

        # MinNewCapacityShare
        if self.table_exists('MinNewCapacityShare'):
            raw = cur.execute(
                'SELECT regions, periods, tech, group_name, maxcapshare FROM main.MinNewCapacityShare'
            ).fetchall()
            load_element(M.MinCapacityShare, raw, self.viable_rt, (0, 2))

        # MaxNewCapacityShare
        if self.table_exists('MaxNewCapacityShare'):
            raw = cur.execute(
                'SELECT regions, periods, tech, group_name, maxcapshare FROM main.MaxNewCapacityShare'
            ).fetchall()
            load_element(M.MaxCapacityShare, raw, self.viable_rt, (0, 2))

        # MinActivityGroup
        if self.table_exists('MinActivityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, t_periods, group_name, min_act_g FROM main.MinActivityGroup '
                    ' WHERE t_periods >= ? AND t_periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, t_periods, group_name, min_act_g FROM main.MinActivityGroup '
                ).fetchall()
            load_element(M.MinActivityGroup, raw)

        # MaxActivityGroup
        if self.table_exists('MaxActivityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, t_periods, group_name, max_act_g FROM main.MaxActivityGroup '
                    ' WHERE t_periods >= ? AND t_periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, t_periods, group_name, max_act_g FROM main.MaxActivityGroup '
                ).fetchall()
            load_element(M.MaxActivityGroup, raw)

        # MinActivityShare
        if self.table_exists('MinActivityShare'):
            raw = cur.execute(
                'SELECT regions, periods, tech, group_name, minactshare FROM main.MinActivityShare'
            ).fetchall()
            load_element(M.MinActivityShare, raw, self.viable_rt, (0, 2))

        # MaxActivityShare
        if self.table_exists('MaxActivityShare'):
            raw = cur.execute(
                'SELECT regions, periods, tech, group_name, maxactshare FROM main.MaxActivityShare'
            ).fetchall()
            load_element(M.MaxActivityShare, raw, self.viable_rt, (0, 2))

        # MaxResource
        if self.table_exists('MaxResource'):
            raw = cur.execute('SELECT regions, tech, maxres FROM main.MaxResource').fetchall()
            load_element(M.MaxResource, raw, self.viable_rt, (0, 1))

        # MaxActivity
        if self.table_exists('MaxActivity'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, tech, maxact FROM main.MaxActivity '
                    'WHERE periods >= ? AND periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, tech, maxact FROM main.MaxActivity '
                ).fetchall()
            load_element(M.MaxActivity, raw, self.viable_rt, (0, 2))

        # MinActivity
        if self.table_exists('MinActivity'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, tech, minact FROM main.MinActivity '
                    'WHERE periods >= ? AND periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, tech, minact FROM main.MinActivity '
                ).fetchall()
            load_element(M.MinActivity, raw, self.viable_rt, (1, 2))

        # MinAnnualCapacityFactor
        if self.table_exists('MinAnnualCapacityFactor'):
            raw = cur.execute(
                'SELECT regions, tech, output_comm, min_acf FROM main.MinAnnualCapacityFactor'
            ).fetchall()
            load_element(M.MinAnnualCapacityFactor, raw, self.viable_rt, (0, 1))

        # MaxAnnualCapacityFactor
        if self.table_exists('MaxAnnualCapacityFactor'):
            raw = cur.execute(
                'SELECT regions, tech, output_comm, max_acf FROM main.MaxAnnualCapacityFactor'
            ).fetchall()
            load_element(M.MaxCapacityFactor, raw, self.viable_rt, (0, 1))

        # GrowthRateMax
        if self.table_exists('GrowthRateMax'):
            raw = cur.execute(
                'SELECT regions, tech, growthrate_max FROM main.GrowthRateMax'
            ).fetchall()
            load_element(M.GrowthRateMax, raw, self.viable_rt, (0, 1))

        # GrowthRateSeed
        if self.table_exists('GrowthRateSeed'):
            raw = cur.execute(
                'SELECT regions, tech, growthrate_seed FROM main.GrowthRateSeed'
            ).fetchall()
            load_element(M.GrowthRateSeed, raw, self.viable_rt, (0, 1))

        # EmissionLimit
        if self.table_exists('EmissionLimit'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, emis_comm, emis_limit FROM main.EmissionLimit '
                    'WHERE periods >= ? AND periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, emis_comm, emis_limit FROM main.EmissionLimit '
                ).fetchall()

            load_element(M.EmissionLimit, raw)

        # EmissionActivity
        # this could be ugly too.  We can have region groups here, so for this to be valid:
        # 1.  r-t-v combo must be valid
        # 2.  The input/output commodities must be viable also
        # 3.  The emission commodities are separate
        # The current emission constraint screens by valid inputs, so if it is NOT
        # built in a particular region, this should still be OK
        if self.table_exists('EmissionActivity'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, emis_comm, input_comm, tech, vintage, output_comm, emis_act '
                    'FROM main.EmissionActivity '
                ).fetchall()
                filtered = [
                    (r, e, i, t, v, o, val)
                    for r, e, i, t, v, o, val in raw
                    if (r, t, v) in self.viable_rtv
                    and i in self.viable_input_comms
                    and o in self.viable_comms
                ]
                load_element(M.EmissionActivity, filtered)
            else:
                raw = cur.execute(
                    'SELECT regions, emis_comm, input_comm, tech, vintage, output_comm, emis_act '
                    'FROM main.EmissionActivity '
                ).fetchall()
                load_element(M.EmissionActivity, raw)

        # LinkedTechs
        # Note:  Both of the linked techs must be viable.  As this is non period/vintage
        #        specific, it should be true that if one is built, the other is also
        if self.table_exists('LinkedTechs'):
            raw = cur.execute(
                'SELECT primary_region, primary_tech, emis_comm, linked_tech FROM main.LinkedTechs'
            ).fetchall()
            load_element(M.LinkedTechs, raw, self.viable_rt, (0, 1))

        # RampUp
        if self.table_exists('RampUp'):
            raw = cur.execute('SELECT regions, tech, ramp_up FROM main.RampUp').fetchall()
            load_element(M.RampUp, raw, self.viable_rt, (0, 1))

        # RampDown
        if self.table_exists('RampDown'):
            raw = cur.execute('SELECT regions, tech, ramp_down FROM main.RampDown').fetchall()
            load_element(M.RampDown, raw, self.viable_rt, (0, 1))

        # CapacityCredit
        if self.table_exists('CapacityCredit'):
            if mi:
                raw = cur.execute(
                    'SELECT regions, periods, tech, vintage, cf_tech FROM main.CapacityCredit '
                    'WHERE periods >= ? AND periods <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT regions, periods, tech, vintage, cf_tech FROM main.CapacityCredit '
                ).fetchall()
            load_element(M.CapacityCredit, raw, self.viable_rtv, (0, 2, 3))

        # PlanningReserveMargin
        if self.table_exists('PlanningReserveMargin'):
            raw = cur.execute(
                'SELECT regions, reserve_margin FROM main.PlanningReserveMargin'
            ).fetchall()
            load_element(M.PlanningReserveMargin, raw)

        # StorageDuration
        if self.table_exists('StorageDuration'):
            raw = cur.execute('SELECT regions, tech, duration FROM main.StorageDuration').fetchall()
            load_element(M.StorageDuration, raw, self.viable_rt, (0, 1))

        # StorageInit
        # TODO:  DB table is busted / removed now... defer!

        # pyomo namespace format has data[namespace][idx]=value
        # the default namespace is None, thus...
        namespace = {None: data}
        if self.debugging:
            for item in namespace[None].items():
                print(item[0], item[1])
        dp = DataPortal(data_dict=namespace)
        toc = time.time()
        logger.debug('Data Portal Load time: %0.5f seconds', (toc - tic))
        return dp
