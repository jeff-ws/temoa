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
from temoa.temoa_model.model_checking.commodity_network_manager import CommodityNetworkManager
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
Created on:  1/21/24

"""

logger = getLogger(__name__)

# the tables below are ones in which we might find regional groups which should be captured
# to make the members of the RegionalGlobalIndices Set in the model.  They need to aggregated
tables_with_regional_groups = {
    'MaxActivity': 'region',
    'MinActivity': 'region',
    'MinAnnualCapacityFactor': 'region',
    'MaxAnnualCapacityFactor': 'region',
    'EmissionLimit': 'region',
    'MinActivityGroup': 'region',
    'MaxActivityGroup': 'region',
    'MinCapacityGroup': 'region',
    'MaxCapacityGroup': 'region',
}


class HybridLoader:
    """
    An instance of the HybridLoader
    """

    def __init__(self, db_connection: Connection, config: TemoaConfig):
        """
        build a loader for an instance.
        :param db_connection: a Connection to the database
        :param config: the config, which controls some options during execution
        """
        self.debugging = False  # for T/S, will print to screen the data load values
        self.con = db_connection
        self.config = config

        self.manager: CommodityNetworkManager | None = None

        # filters for myopic ops
        self.viable_techs: set[str] = set()
        self.viable_comms: set[str] = set()
        self.viable_input_comms: set[str] = set()
        self.viable_output_comms: set[str] = set()
        self.viable_vintages: set[int] = set()
        self.viable_ritvo = set()
        self.viable_rtv: set[tuple[str, str, int]] = set()
        self.viable_rt: set[tuple[str, str]] = set()
        self.viable_rtt = set()  # to support scanning LinkedTech
        self.efficiency_values: list[tuple] = []

    def source_trace_only(self, make_plots: bool = False, myopic_index: MyopicIndex | None = None):
        if myopic_index and not isinstance(myopic_index, MyopicIndex):
            raise ValueError('myopic_index must be an instance of MyopicIndex')
        self._source_trace(make_plots, myopic_index)
        self.manager = None  # to prevent possible out-of-synch build from stale data

    def _source_trace(self, make_plots: bool, myopic_index: MyopicIndex = None):
        network_data = network_model_data.build(self.con, myopic_index=myopic_index)
        cur = self.con.cursor()
        # need periods to execute the source check by [r, p].  At this point, we can only pull from DB
        periods = {
            period for (period, *_) in cur.execute("SELECT period FROM TimePeriod WHERE flag = 'f'")
        }
        # we need to exclude the last period, it is a non-demand year
        periods = sorted(periods)[:-1]

        if myopic_index:
            periods = {
                p for p in periods if myopic_index.base_year <= p <= myopic_index.last_demand_year
            }
        self.manager = CommodityNetworkManager(periods=periods, network_data=network_data)
        self.manager.analyze_network()
        if make_plots:
            self.manager.make_commodity_plots(self.config)

    def _build_efficiency_dataset(
        self, use_raw_data=False, myopic_index: MyopicIndex | None = None
    ):
        """
        Build the efficiency dataset.  For myopic mode, this means pull from MyopicEfficiency table
        and we cannot use raw data.  For other modes, we can either use raw data or the filtered data
        provided by the manager (normal)
        :param use_raw_data: if True, use raw data (without source-trace filtering) for build
        :param myopic_index: the myopic index to use (or None for other modes)
        :return:
        """
        if myopic_index and use_raw_data:
            raise RuntimeError('Cannot build from raw data in myopic mode...  Likely coding error.')
        cur = self.con.cursor()
        # pull the data based on whether myopic/not
        if myopic_index:
            # pull from MyopicEfficiency, and filter by myopic index years
            contents = cur.execute(
                'SELECT region, input_comm, tech, vintage, output_comm, efficiency, lifetime  '
                'FROM MyopicEfficiency '
                'WHERE vintage + lifetime > ?',
                (myopic_index.base_year,),
            ).fetchall()
        else:
            # pull from regular Efficiency table
            contents = cur.execute(
                'SELECT region, input_comm, tech, vintage, output_comm, efficiency, NULL FROM main.Efficiency'
            ).fetchall()

        # filter/don't filter.
        if use_raw_data:
            efficiency_entries = [row for row in contents]
            # need to build filters to include everything in the raw efficiency data
            # this will still help filter anything spurious that is not covered by the data
            # in the efficiency table
            self._clear_filters()
            for row in contents:
                r, i, t, v, o, _, _ = row
                self.viable_ritvo.add((r, i, t, v, o))
                self.viable_rtv.add((r, t, v))
                self.viable_rt.add((r, t))
                self.viable_techs.add(t)
                self.viable_vintages.add(v)
                self.viable_input_comms.add(i)
                self.viable_output_comms.add(o)
            self.viable_comms = self.viable_input_comms | self.viable_output_comms
            self.viable_rtt = {(r, t1, t2) for r, t1 in self.viable_rt for t2 in self.viable_techs}

        else:  # (always must when myopic)
            self._clear_filters()
            filts = {}
            if self.manager:
                filts = self.manager.build_filters()
            else:
                raise RuntimeError('trying to filter, but manager has not analyzed network yet.')
            self.viable_ritvo = filts['ritvo']
            self.viable_rtv = filts['rtv']
            self.viable_rt = filts['rt']
            self.viable_techs = filts['t']
            self.viable_input_comms = filts['ic']
            self.viable_vintages = filts['v']
            self.viable_output_comms = filts['oc']
            self.viable_comms = self.viable_input_comms | self.viable_output_comms
            self.viable_rtt = {(r, t1, t2) for r, t1 in self.viable_rt for t2 in self.viable_techs}
            efficiency_entries = {
                (r, i, t, v, o, eff)
                for r, i, t, v, o, eff, lifetime in contents
                if (r, i, t, v, o) in self.viable_ritvo
            }
        logger.debug('polled %d elements from MyopicEfficiency table', len(efficiency_entries))

        # book the EfficiencyTable
        # we should sort here for deterministic results after pulling from set
        self.efficiency_values = sorted(efficiency_entries)

    @deprecated.deprecated('outdated...use source tracing approach')
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
            "SELECT name FROM main.Commodity WHERE flag = 'p' OR flag = 's'"
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

    def load_data_portal(self, myopic_index: MyopicIndex | None = None) -> DataPortal:
        """
        Create and Load a Data Portal.  If source tracing is enabled in the config, the source trace will
        be executed and filtered data will be used.  Without source-trace, raw (unfiltered) data will be loaded.
        :param myopic_index: the MyopicIndex for myopic run.  None for other modes
        :return:
        """
        # the general plan:
        # 0. determine if source trace needs to be done, and do it
        # 1. build the efficiency table
        # 2. iterate through the model elements that are directly read from data
        # 3. use SQL query to get the full table
        # 4. (OPTIONALLY) filter it, as needed for myopic
        # 5. load it into the data dictionary
        logger.info('Loading data portal')

        # some logic checking...
        if myopic_index is not None:
            if not isinstance(myopic_index, MyopicIndex):
                raise ValueError(f'received an illegal entry for the myopic index: {myopic_index}')
            if self.config.scenario_mode != TemoaMode.MYOPIC:
                raise RuntimeError(
                    'Myopic Index passed to data portal build, but mode is not Myopic.... '
                    'Likely code error.'
                )
        elif myopic_index is None and self.config.scenario_mode == TemoaMode.MYOPIC:
            raise RuntimeError(
                'Mode is myopic, but no MyopicIndex specified in data portal build.... Likely code '
                'error.'
            )

        if self.config.source_trace or self.config.scenario_mode == TemoaMode.MYOPIC:
            use_raw_data = False
            self._source_trace(
                make_plots=self.config.plot_commodity_network, myopic_index=myopic_index
            )
        else:
            use_raw_data = True

        # build the Efficiency Dataset
        self._build_efficiency_dataset(use_raw_data=use_raw_data, myopic_index=myopic_index)

        mi = myopic_index  # convenience

        # time the creation of the data portal
        tic = time.time()
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
                            elif validation is self.viable_rtv:
                                data[c.name] = [
                                    t
                                    for t in values
                                    if (t[val_loc[0]], t[val_loc[1]], t[val_loc[2]])
                                    in self.viable_rtv
                                ]
                            elif validation is self.viable_rt:
                                data[c.name] = [
                                    t
                                    for t in values
                                    if (t[val_loc[0]], t[val_loc[1]]) in self.viable_rt
                                ]
                            elif validation is self.viable_vintages:
                                data[c.name] = [
                                    t for t in values if t[val_loc[0]] in self.viable_vintages
                                ]
                            elif validation is self.viable_output_comms:
                                data[c.name] = [
                                    t for t in values if t[val_loc[0]] in self.viable_output_comms
                                ]
                            else:
                                raise NotImplementedError(
                                    f'that validator is not yet incorporated for use in validating: {c.name}'
                                )
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

        def load_indexed_set(indexed_set: Set, index_value, element, element_validator):
            """
            load an element into an indexed set in the data store
            :param indexed_set: the name of the pyomo Set
            :param index_value: the index value to load into
            :param element: the value to add to the indexed set
            :param element_validator: a set of legal elements for the element to be added
            :return: None
            """
            if element not in element_validator:
                return
            data_store = data.get(indexed_set.name, defaultdict(list))
            data_store[index_value].append(element)
            data[indexed_set.name] = data_store

        M: TemoaModel = TemoaModel()  # for typing purposes only
        cur = self.con.cursor()

        #   === TIME SETS ===

        # time_exist
        if mi:
            raw = cur.execute(
                'SELECT period FROM main.TimePeriod  WHERE period < ? ORDER BY sequence',
                (mi.base_year,),
            ).fetchall()
        else:
            raw = cur.execute(
                "SELECT period FROM main.TimePeriod WHERE flag = 'e' ORDER BY sequence"
            ).fetchall()
        load_element(M.time_exist, raw)

        # time_future
        if mi:
            raw = cur.execute(
                'SELECT period FROM main.TimePeriod WHERE '
                'period >= ? AND period <= ? ORDER BY sequence',
                (mi.base_year, mi.last_year),
            ).fetchall()
        else:
            raw = cur.execute(
                "SELECT period FROM main.TimePeriod WHERE flag = 'f' ORDER BY sequence"
            ).fetchall()
        load_element(M.time_future, raw)

        # time_of_day
        raw = cur.execute('SELECT tod FROM main.TimeOfDay ORDER BY sequence').fetchall()
        load_element(M.time_of_day, raw)

        # time_season
        raw = cur.execute('SELECT season FROM main.TimeSeason ORDER BY sequence').fetchall()
        load_element(M.time_season, raw)

        # myopic_base_year
        if mi:
            raw = cur.execute(
                "SELECT value from MetaData WHERE element == 'myopic_base_year'"
            ).fetchall()
            # load as a singleton...
            if not raw:
                raise ValueError('No myopic_base_year found in MetaData table.')
            data[M.MyopicBaseyear.name] = {None: int(raw[0][0])}

        #  === REGION SETS ===

        # regions
        raw = cur.execute('SELECT region FROM main.Region').fetchall()
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
        raw = cur.execute("SELECT tech FROM main.Technology WHERE flag = 'r'").fetchall()
        load_element(M.tech_resource, raw, self.viable_techs)

        # tech_production
        raw = cur.execute("SELECT tech FROM main.Technology WHERE flag LIKE 'p%'").fetchall()
        load_element(M.tech_production, raw, self.viable_techs)

        # tech_uncap
        try:
            raw = cur.execute('SELECT tech FROM main.Technology WHERE unlim_cap > 0').fetchall()
            load_element(M.tech_uncap, raw, self.viable_techs)
        except OperationalError:
            logger.info(
                'The current database does not support non-capacity techs and should be upgraded.'
            )

        # tech_baseload
        raw = cur.execute("SELECT tech FROM main.Technology WHERE flag = 'pb'").fetchall()
        load_element(M.tech_baseload, raw, self.viable_techs)

        # tech_storage
        raw = cur.execute("SELECT tech FROM main.Technology WHERE flag = 'ps'").fetchall()
        load_element(M.tech_storage, raw, self.viable_techs)

        # tech_reserve
        raw = cur.execute('SELECT tech FROM Technology WHERE reserve > 0').fetchall()
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

        # tech_curtailment
        raw = cur.execute('SELECT tech FROM Technology WHERE curtail > 0').fetchall()
        load_element(M.tech_curtailment, raw, self.viable_techs)

        # tech_flex
        raw = cur.execute('SELECT tech FROM Technology WHERE flex > 0').fetchall()
        load_element(M.tech_flex, raw, self.viable_techs)

        # tech_exchange
        raw = cur.execute('SELECT tech FROM Technology WHERE exchange > 0').fetchall()
        load_element(M.tech_exchange, raw, self.viable_techs)

        # groups & tech_groups (supports RPS and general tech grouping)
        if self.table_exists('TechGroup'):
            raw = cur.execute('SELECT group_name FROM main.TechGroup').fetchall()
            load_element(M.tech_group_names, raw)

        if self.table_exists('TechGroupMember'):
            raw = cur.execute('SELECT group_name, tech FROM main.TechGroupMember').fetchall()
            for row in raw:
                load_indexed_set(
                    M.tech_group_members,
                    index_value=row[0],
                    element=row[1],
                    element_validator=self.viable_techs,
                )

        # tech_annual
        raw = cur.execute('SELECT tech FROM Technology WHERE annual > 0').fetchall()
        load_element(M.tech_annual, raw, self.viable_techs)

        # tech_variable
        raw = cur.execute('SELECT tech FROM Technology WHERE variable > 0').fetchall()
        load_element(M.tech_variable, raw, self.viable_techs)

        # tech_retirement
        raw = cur.execute('SELECT tech FROM Technology WHERE retire > 0').fetchall()
        load_element(M.tech_retirement, raw, self.viable_techs)

        #  === COMMODITIES ===

        # commodity_demand
        raw = cur.execute("SELECT name FROM main.Commodity WHERE flag = 'd'").fetchall()
        load_element(M.commodity_demand, raw, self.viable_comms)

        # commodity_emissions
        # currently NOT validated against anything... shouldn't be a problem ?
        raw = cur.execute("SELECT name FROM main.Commodity WHERE flag = 'e'").fetchall()
        load_element(M.commodity_emissions, raw)

        # commodity_physical
        raw = cur.execute(
            "SELECT name FROM main.Commodity WHERE flag = 'p' OR flag = 's'"
        ).fetchall()
        # The model enforces 0 symmetric difference between the physical commodities
        # and the input commodities, so we need to include only the viable INPUTS
        load_element(M.commodity_physical, raw, self.viable_input_comms)

        # commodity_source
        raw = cur.execute("SELECT name FROM main.Commodity WHERE flag = 's'").fetchall()
        load_element(M.commodity_source, raw, self.viable_input_comms)

        #  === PARAMS ===

        # Efficiency
        if mi:
            # use what we have already computed
            raw = self.efficiency_values
        else:
            raw = cur.execute(
                'SELECT region, input_comm, tech, vintage, output_comm, efficiency '
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
                'SELECT MAX(period) FROM main.TimePeriod WHERE period < ?', (mi.base_year,)
            ).fetchone()
            previous_period = raw[0]
            # noinspection SqlUnused
            raw = cur.execute(
                'SELECT region, tech, vintage, capacity FROM main.OutputNetCapacity '
                ' WHERE period = ? '
                'UNION '
                '  SELECT region, tech, vintage, capacity FROM main.ExistingCapacity ',
                (previous_period,),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT region, tech, vintage, capacity FROM main.ExistingCapacity'
            ).fetchall()
        load_element(M.ExistingCapacity, raw, self.viable_rtv, (0, 1, 2))

        # GlobalDiscountRate
        raw = cur.execute(
            "SELECT value FROM main.MetaDataReal WHERE element = 'global_discount_rate'"
        ).fetchall()
        # do this separately as it is non-indexed, so we need to make a mapping with None
        data[M.GlobalDiscountRate.name] = {None: raw[0][0]}

        # SegFrac
        raw = cur.execute('SELECT season, tod, segfrac FROM main.TimeSegmentFraction').fetchall()
        load_element(M.SegFrac, raw)

        # DemandSpecificDistribution
        raw = cur.execute(
            'SELECT region, season, tod, demand_name, dds FROM main.DemandSpecificDistribution'
        ).fetchall()
        load_element(M.DemandSpecificDistribution, raw)

        # Demand
        if mi:
            raw = cur.execute(
                'SELECT region, period, commodity, demand FROM main.Demand '
                'WHERE period >= ? AND period <= ?',
                (mi.base_year, mi.last_demand_year),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT region, period, commodity, demand FROM main.Demand '
            ).fetchall()
        load_element(M.Demand, raw)

        # RescourceBound
        # TODO:  later, it isn't used RN anyhow.

        # CapacityToActivity
        raw = cur.execute('SELECT region, tech, c2a FROM main.CapacityToActivity ').fetchall()
        load_element(M.CapacityToActivity, raw, self.viable_rt, (0, 1))

        # CapacityFactorTech
        raw = cur.execute(
            'SELECT region, season, tod, tech, factor ' 'FROM main.CapacityFactorTech'
        ).fetchall()
        load_element(M.CapacityFactorTech, raw, self.viable_rt, (0, 3))

        # CapacityFactorProcess
        raw = cur.execute(
            'SELECT region, season, tod, tech, vintage, factor ' ' FROM main.CapacityFactorProcess'
        ).fetchall()
        load_element(M.CapacityFactorProcess, raw, self.viable_rtv, (0, 3, 4))

        # LifetimeTech
        raw = cur.execute('SELECT region, tech, lifetime FROM main.LifetimeTech').fetchall()
        load_element(M.LifetimeTech, raw, self.viable_rt, val_loc=(0, 1))

        # LifetimeProcess
        raw = cur.execute(
            'SELECT region, tech, vintage, lifetime FROM main.LifetimeProcess'
        ).fetchall()
        load_element(M.LifetimeProcess, raw, self.viable_rtv, val_loc=(0, 1, 2))

        # LoanLifetimeTech
        raw = cur.execute('SELECT region, tech, lifetime FROM main.LoanLifetimeTech').fetchall()
        load_element(M.LoanLifetimeTech, raw, self.viable_rt, (0, 1))

        # TechInputSplit
        if mi:
            raw = cur.execute(
                'SELECT region, period, input_comm, tech, min_proportion FROM main.TechInputSplit '
                'WHERE period >= ? AND period <= ?',
                (mi.base_year, mi.last_demand_year),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT region, period, input_comm, tech, min_proportion FROM main.TechInputSplit '
            ).fetchall()
        load_element(M.TechInputSplit, raw, self.viable_rt, (0, 3))

        # TechInputSplitAverage
        if self.table_exists('TechInputSplitAverage'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, input_comm, tech, min_proportion '
                    'FROM main.TechInputSplitAverage '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, input_comm, tech, min_proportion '
                    'FROM main.TechInputSplitAverage '
                ).fetchall()
            load_element(M.TechInputSplitAverage, raw, self.viable_rt, (0, 3))

        # TechOutputSplit
        if self.table_exists('TechOutputSplit'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, tech, output_comm, min_proportion FROM main.TechOutputSplit '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, tech, output_comm, min_proportion FROM main.TechOutputSplit '
                ).fetchall()
            load_element(M.TechOutputSplit, raw, self.viable_rt, (0, 2))

        # RenewablePortfolioStandard
        if self.table_exists('RPSRequirement'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, tech_group, requirement FROM main.RPSRequirement '
                    ' WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, tech_group, requirement FROM main.RPSRequirement '
                ).fetchall()
            load_element(M.RenewablePortfolioStandard, raw)

        # CostFixed
        if mi:
            raw = cur.execute(
                'SELECT region, period, tech, vintage, cost FROM main.CostFixed '
                'WHERE period >= ? AND period <= ?',
                (mi.base_year, mi.last_demand_year),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT region, period, tech, vintage, cost FROM main.CostFixed '
            ).fetchall()
        load_element(M.CostFixed, raw, self.viable_rtv, val_loc=(0, 2, 3))

        # CostInvest
        # exclude "existing" vintages by screening for base year and beyond.
        # the "viable_rtv" will filter anything beyond view
        if mi:
            raw = cur.execute(
                'SELECT region, tech, vintage, cost FROM main.CostInvest ' 'WHERE vintage >= ?',
                (mi.base_year,),
            ).fetchall()
        else:
            raw = cur.execute('SELECT region, tech, vintage, cost FROM main.CostInvest ').fetchall()
        load_element(M.CostInvest, raw, self.viable_rtv, (0, 1, 2))

        # CostVariable
        if mi:
            raw = cur.execute(
                'SELECT region, period, tech, vintage, cost FROM main.CostVariable '
                'WHERE period >= ? AND period <= ?',
                (mi.base_year, mi.last_demand_year),
            ).fetchall()
        else:
            raw = cur.execute(
                'SELECT region, period, tech, vintage, cost FROM main.CostVariable '
            ).fetchall()
        load_element(M.CostVariable, raw, self.viable_rtv, (0, 2, 3))

        # CostEmissions (and supporting index set)
        if self.table_exists('CostEmission'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, emis_comm from main.CostEmission '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
                load_element(M.CostEmission_rpe, raw, self.viable_output_comms, (2,))

                raw = cur.execute(
                    'SELECT region, period, emis_comm, cost from main.CostEmission '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
                load_element(M.CostEmission, raw, self.viable_output_comms, (2,))
            else:
                raw = cur.execute(
                    'SELECT region, period, emis_comm from main.CostEmission '
                ).fetchall()
                load_element(M.CostEmission_rpe, raw, self.viable_output_comms, (2,))

                raw = cur.execute(
                    'SELECT region, period, emis_comm, cost from main.CostEmission '
                ).fetchall()
                load_element(M.CostEmission, raw, self.viable_output_comms, (2,))

        # DefaultLoanRate
        raw = cur.execute(
            "SELECT value FROM main.MetaDataReal WHERE element = 'default_loan_rate'"
        ).fetchall()
        # do this separately as it is non-indexed, so we need to make a mapping with None
        data[M.DefaultLoanRate.name] = {None: raw[0][0]}

        # LoanRate
        if mi:
            raw = cur.execute(
                'SELECT region, tech, vintage, rate FROM main.LoanRate ' 'WHERE vintage >= ?',
                (mi.base_year,),
            ).fetchall()
        else:
            raw = cur.execute('SELECT region, tech, vintage, rate FROM main.LoanRate ').fetchall()

        load_element(M.LoanRate, raw, self.viable_rtv, (0, 1, 2))

        # MinCapacity
        if self.table_exists('MinCapacity'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, tech, min_cap FROM main.MinCapacity '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, tech, min_cap FROM main.MinCapacity '
                ).fetchall()
            load_element(M.MinCapacity, raw, self.viable_rt, (0, 2))

        # MaxCapacity
        if self.table_exists('MaxCapacity'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, tech, max_cap FROM main.MaxCapacity '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, tech, max_cap FROM main.MaxCapacity '
                ).fetchall()
            load_element(M.MaxCapacity, raw, self.viable_rt, (0, 2))

        # MinNewCap
        if self.table_exists('MinNewCapacity'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, tech, min_cap FROM main.MinNewCapacity '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, tech, min_cap FROM main.MinNewCapacity '
                ).fetchall()
            load_element(M.MinNewCapacity, raw, self.viable_rt, (0, 2))

        # MaxNewCap
        if self.table_exists('MaxNewCapacity'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, tech, max_cap FROM main.MaxNewCapacity '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, tech, max_cap FROM main.MaxNewCapacity '
                ).fetchall()
            load_element(M.MaxNewCapacity, raw, self.viable_rt, (0, 2))

        # MaxCapacityGroup
        if self.table_exists('MaxCapacityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, group_name, max_cap FROM main.MaxCapacityGroup '
                    ' WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, group_name, max_cap FROM main.MaxCapacityGroup '
                ).fetchall()
            load_element(M.MaxCapacityGroup, raw)

        # MinCapacityGroup
        if self.table_exists('MinCapacityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, group_name, min_cap FROM main.MinCapacityGroup '
                    ' WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, group_name, min_cap FROM main.MinCapacityGroup '
                ).fetchall()
            load_element(M.MinCapacityGroup, raw)

        # MinNewCapacityGroup
        if self.table_exists('MinNewCapacityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, group_name, min_new_cap FROM main.MinNewCapacityGroup '
                    ' WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, group_name, min_new_cap FROM main.MinNewCapacityGroup '
                ).fetchall()
            load_element(M.MinNewCapacityGroup, raw)

        # MaxNewCapacityGroup
        if self.table_exists('MaxNewCapacityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, group_name, max_new_cap FROM main.MaxNewCapacityGroup '
                    ' WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, group_name, max_new_cap FROM main.MaxNewCapacityGroup '
                ).fetchall()
            load_element(M.MaxNewCapacityGroup, raw)

        # MinCapacityShare
        if self.table_exists('MinCapacityShare'):
            raw = cur.execute(
                'SELECT region, period, tech, group_name, min_proportion FROM main.MinCapacityShare'
            ).fetchall()
            load_element(M.MinCapacityShare, raw, self.viable_rt, (0, 2))

        # MaxCapacityShare
        if self.table_exists('MaxCapacityShare'):
            raw = cur.execute(
                'SELECT region, period, tech, group_name, max_proportion FROM main.MaxCapacityShare'
            ).fetchall()
            load_element(M.MaxCapacityShare, raw, self.viable_rt, (0, 2))

        # MinNewCapacityShare
        if self.table_exists('MinNewCapacityShare'):
            raw = cur.execute(
                'SELECT region, period, tech, group_name, max_proportion FROM main.MinNewCapacityShare'
            ).fetchall()
            load_element(M.MinCapacityShare, raw, self.viable_rt, (0, 2))

        # MaxNewCapacityShare
        if self.table_exists('MaxNewCapacityShare'):
            raw = cur.execute(
                'SELECT region, period, tech, group_name, max_proportion FROM main.MaxNewCapacityShare'
            ).fetchall()
            load_element(M.MaxCapacityShare, raw, self.viable_rt, (0, 2))

        # MinActivityGroup
        if self.table_exists('MinActivityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, group_name, min_act FROM main.MinActivityGroup '
                    ' WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, group_name, min_act FROM main.MinActivityGroup '
                ).fetchall()
            load_element(M.MinActivityGroup, raw)

        # MaxActivityGroup
        if self.table_exists('MaxActivityGroup'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, group_name, max_act FROM main.MaxActivityGroup '
                    ' WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, group_name, max_act FROM main.MaxActivityGroup '
                ).fetchall()
            load_element(M.MaxActivityGroup, raw)

        # MinActivityShare
        if self.table_exists('MinActivityShare'):
            raw = cur.execute(
                'SELECT region, period, tech, group_name, min_proportion FROM main.MinActivityShare'
            ).fetchall()
            load_element(M.MinActivityShare, raw, self.viable_rt, (0, 2))

        # MaxActivityShare
        if self.table_exists('MaxActivityShare'):
            raw = cur.execute(
                'SELECT region, period, tech, group_name, max_proportion FROM main.MaxActivityShare'
            ).fetchall()
            load_element(M.MaxActivityShare, raw, self.viable_rt, (0, 2))

        # MaxResource
        if self.table_exists('MaxResource'):
            raw = cur.execute('SELECT region, tech, max_res FROM main.MaxResource').fetchall()
            load_element(M.MaxResource, raw, self.viable_rt, (0, 1))

        # MaxActivity
        if self.table_exists('MaxActivity'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, tech, max_act FROM main.MaxActivity '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, tech, max_act FROM main.MaxActivity '
                ).fetchall()
            load_element(M.MaxActivity, raw, self.viable_rt, (0, 2))

        # MinActivity
        if self.table_exists('MinActivity'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, tech, min_act FROM main.MinActivity '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, tech, min_act FROM main.MinActivity '
                ).fetchall()
            load_element(M.MinActivity, raw, self.viable_rt, (1, 2))

        # MinAnnualCapacityFactor
        if self.table_exists('MinAnnualCapacityFactor'):
            raw = cur.execute(
                'SELECT region, tech, output_comm, factor FROM main.MinAnnualCapacityFactor'
            ).fetchall()
            load_element(M.MinAnnualCapacityFactor, raw, self.viable_rt, (0, 1))

        # MaxAnnualCapacityFactor
        if self.table_exists('MaxAnnualCapacityFactor'):
            raw = cur.execute(
                'SELECT region, tech, output_comm, factor FROM main.MaxAnnualCapacityFactor'
            ).fetchall()
            load_element(M.MaxAnnualCapacityFactor, raw, self.viable_rt, (0, 1))

        # GrowthRateMax
        if self.table_exists('GrowthRateMax'):
            raw = cur.execute('SELECT region, tech, rate FROM main.GrowthRateMax').fetchall()
            load_element(M.GrowthRateMax, raw, self.viable_rt, (0, 1))

        # GrowthRateSeed
        if self.table_exists('GrowthRateSeed'):
            raw = cur.execute('SELECT region, tech, seed FROM main.GrowthRateSeed').fetchall()
            load_element(M.GrowthRateSeed, raw, self.viable_rt, (0, 1))

        # EmissionLimit
        if self.table_exists('EmissionLimit'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, emis_comm, value FROM main.EmissionLimit '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, emis_comm, value FROM main.EmissionLimit '
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
                    'SELECT region, emis_comm, input_comm, tech, vintage, output_comm, activity '
                    'FROM main.EmissionActivity '
                ).fetchall()
                filtered = [
                    (r, e, i, t, v, o, val)
                    for r, e, i, t, v, o, val in raw
                    if (r, i, t, v, o) in self.viable_ritvo
                ]
                load_element(M.EmissionActivity, filtered)
            else:
                raw = cur.execute(
                    'SELECT region, emis_comm, input_comm, tech, vintage, output_comm, activity '
                    'FROM main.EmissionActivity '
                ).fetchall()
                load_element(M.EmissionActivity, raw)

        # LinkedTechs
        # Note:  Both of the linked techs must be viable.  As this is non period/vintage
        #        specific, it should be true that if one is built, the other is also
        if self.table_exists('LinkedTech'):
            raw = cur.execute(
                'SELECT primary_region, primary_tech, emis_comm, driven_tech FROM main.LinkedTech'
            ).fetchall()
            load_element(M.LinkedTechs, raw, self.viable_rtt, (0, 1, 3))

        # RampUp
        if self.table_exists('RampUp'):
            raw = cur.execute('SELECT region, tech, rate FROM main.RampUp').fetchall()
            load_element(M.RampUp, raw, self.viable_rt, (0, 1))

        # RampDown
        if self.table_exists('RampDown'):
            raw = cur.execute('SELECT region, tech, rate FROM main.RampDown').fetchall()
            load_element(M.RampDown, raw, self.viable_rt, (0, 1))

        # CapacityCredit
        if self.table_exists('CapacityCredit'):
            if mi:
                raw = cur.execute(
                    'SELECT region, period, tech, vintage, credit FROM main.CapacityCredit '
                    'WHERE period >= ? AND period <= ?',
                    (mi.base_year, mi.last_demand_year),
                ).fetchall()
            else:
                raw = cur.execute(
                    'SELECT region, period, tech, vintage, credit FROM main.CapacityCredit '
                ).fetchall()
            load_element(M.CapacityCredit, raw, self.viable_rtv, (0, 2, 3))

        # PlanningReserveMargin
        if self.table_exists('PlanningReserveMargin'):
            raw = cur.execute('SELECT region, margin FROM main.PlanningReserveMargin').fetchall()
            load_element(M.PlanningReserveMargin, raw)

        # StorageDuration
        if self.table_exists('StorageDuration'):
            raw = cur.execute('SELECT region, tech, duration FROM main.StorageDuration').fetchall()
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
