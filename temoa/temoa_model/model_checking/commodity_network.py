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
Created on:  3/11/24

"""
from collections import defaultdict
from itertools import chain
from logging import getLogger

from temoa.temoa_model.model_checking.commodity_graph import graph_connections
from temoa.temoa_model.model_checking.network_model_data import NetworkModelData, Tech
from temoa.temoa_model.temoa_config import TemoaConfig

logger = getLogger(__name__)


class CommodityNetwork:
    """
    class to hold the data and the network for a particular region/period
    """

    def __init__(self, region, period: int, model_data: NetworkModelData):
        """
        make the network
        :param region: region
        :param period: period
        :param model_data: a NetworkModelData object
        """
        # check the marking of source commodities first, as the db may not be configured for source check...
        self.model_data = model_data
        if not self.model_data.source_commodities:
            logger.error(
                'No source commodities discovered when initializing Commodity Network.  '
                'Have source commodities been identified in commodities '
                "table with 's'?"
            )
            raise ValueError(
                'Attempted to do source trace with no source commodities marked.  '
                'Have source commodities been identified in commodities '
                "table with 's'?"
            )
        self.demand_orphans: set[tuple] = set()
        self.other_orphans: set[tuple] = set()
        self.good_connections: set[tuple] = set()
        self.region = region
        self.period = period
        # the cataloguing of inputs/outputs by tech is needed for implicit links like via emissions in LinkedTech
        self.tech_inputs: dict[str, set[str]] = defaultdict(set)
        self.tech_outputs: dict[str, set[str]] = defaultdict(set)
        self.connections: dict[str, set[tuple]] = defaultdict(set)
        """All connections in the model {oc: {(ic, tech), ...}}"""
        self.orig_connex: set[tuple] = set()

        if not self.model_data.demand_commodities[self.region, self.period]:
            raise ValueError(
                f'No demand commodities discovered in region {self.region} period {self.period}.  Check '
                f'Demand table data'
            )
        # dev note:  This code was originally designed/tested to run on tuples of (ic, tech_name, oc)
        #            since the implementation of Tech named tuple, we could switch over to that soon,
        #            but it will be work to re-work the tests.  The networks are smaller this way
        #            because of reduced redundant links for multi-vintages, but we will have to
        #            filter the Tech tuples for output generation against the names...

        # scan techs for this r, p
        for tech in self.model_data.available_techs[self.region, self.period]:
            self.connections[tech.oc].add((tech.ic, tech.tech_name))
            self.tech_inputs[tech.tech_name].add(tech.ic)
            self.tech_outputs[tech.tech_name].add(tech.oc)

        # make synthetic connection between linked techs
        self.connect_linked_techs()

        # TODO:  perhaps sockets later to account for inter-regional links, for now,
        #  we will just look at internal connex
        # # set of exchange techs FROM this region that supply commodity through link
        # # {tech: set(output commodities)}
        # self.output_sockets: dict[str, set[str]] = dict()
        # self.input_sockets: ...

    def get_valid_tech(self) -> set[Tech]:
        return {
            tech
            for tech in self.model_data.available_techs[self.region, self.period]
            if (tech.ic, tech.tech_name, tech.oc) in self.good_connections
        }

    def get_demand_side_orphans(self) -> set[Tech]:
        return {
            tech
            for tech in self.model_data.available_techs[self.region, self.period]
            if (tech.ic, tech.tech_name, tech.oc) in self.demand_orphans
        }

    def get_other_orphans(self) -> set[Tech]:
        return {
            tech
            for tech in self.model_data.available_techs[self.region, self.period]
            if (tech.ic, tech.tech_name, tech.oc) in self.other_orphans
        }

    def connect_linked_techs(self):
        # add implicit connections from linked tech...  Meaning:  For the DRIVEN tech, we need to make an
        # implicit connection back to the output of the driver (even though it is actually feeding off of
        # the emission) so that the driven tech is not orphaned.
        for r, driver, emission, driven in self.model_data.available_linked_techs:
            if r == self.region:
                # check that the driven tech only has 1 input....
                # Dev Note:  It isn't clear how to link to a driven tech with multiple inputs as the linkage
                # is via the emission of the driver, and establishing links to all inputs of the driven
                # would likely supply false assurance that the multiple inputs were all viable
                if len(self.tech_inputs[driven]) > 1:
                    raise ValueError(
                        'Multiple input commodities detected for a driven Linked Tech.  This is '
                        'currently not supported because establishing the validity of the multiple '
                        'input commodities is not possible with current linkage data.'
                    )
                # check that the driver & driven techs both exist
                if driver in self.tech_outputs and driven in self.tech_outputs:  # we're gtg.
                    for oc in self.tech_outputs[driver]:
                        # we need to link the commodities via an implied link
                        # so the oc from the driver needs to be linked to the ic for the driven by a 'fake' tech
                        self.connections[oc].update(
                            {(ic, '<<linked tech>>') for ic in self.tech_inputs[driven]}
                        )

                # else, document errors in linkage...
                elif driver not in self.tech_outputs and driven not in self.tech_outputs:
                    # neither tech is present, not a problem
                    logger.debug(
                        'Note (no action reqd.):  Neither linked tech %s nor %s are active in region %s, period %s',
                        driver,
                        driven,
                        self.region,
                        self.period,
                    )
                elif driver in self.tech_outputs and driven not in self.tech_outputs:
                    logger.info(
                        'No driven linked tech available for driver %s in regions %s, period %d.  '
                        'Driver may function without it.',
                        driver,
                        self.region,
                        self.period,
                    )
                # the driver tech is not available, a problem because the driven
                # could be allowed to run without constraint.
                else:
                    logger.warning(
                        'Driven linked tech %s is not connected to an active or available '
                        'driver in region %s, period %d',
                        driven,
                        self.region,
                        self.period,
                    )
                    raise ValueError(
                        'Driven linked tech %s is not connected to a driver.  See log file details. \n'
                    )

    def analyze_network(self):
        # dev note:  send a copy of connections...
        # it is consumed by the function.  (easier than managing it in the recursion)
        discovered_sources, demand_side_connections = _visited_dfs(
            self.model_data.demand_commodities[self.region, self.period],
            self.model_data.source_commodities,
            self.connections.copy(),
        )
        self.good_connections = _mark_good_connections(
            good_ic=discovered_sources, connections=demand_side_connections.copy()
        )

        logger.info(
            'Got %d good technologies (possibly multi-vintage) from %d techs in region %s, period %d',
            len(self.good_connections),
            len(tuple(chain(*self.connections.values()))),
            self.region,
            self.period,
        )

        # Sort out the demand-side and supply-side orphans
        # Now we should have:
        # 1.  The original connections
        # 2.  The demand-side connections from the first search (all things backward from Demands)
        # 3.  The "good" connections that have full linkage from source back to demand

        # So we can infer (these are set operations):
        # 4.  demand-side orphans = demand_side_connections - good_connections
        # 5.  other orphans = original_connections - demand_side_connections - good_connections

        # flat lists are easier for comparison, so...
        self.orig_connex: set[tuple] = {
            (ic, tech, oc) for oc in self.connections for (ic, tech) in self.connections[oc]
        }
        # dev note:  recall, the demand connex are inventoried by IC for use in the 2nd search, so we need to poll by IC...
        demand_connex: set[tuple] = {
            (ic, tech, oc)
            for ic in demand_side_connections
            for (oc, tech) in demand_side_connections[ic]
        }

        self.demand_orphans = demand_connex - self.good_connections
        self.other_orphans = self.orig_connex - demand_connex - self.good_connections

        if self.other_orphans:
            logger.info(
                'Source tracing revealed %d orphaned processes in region %s, period %d.  '
                'Enable DEBUG level logging with "-d" to have them logged',
                len(self.other_orphans),
                self.region,
                self.period,
            )
        for orphan in sorted(self.other_orphans, key=lambda x: x[1]):
            logger.debug(
                'Bad (orphan/disconnected) process should be investigated/removed: \n'
                '   %s in region %s, period %d',
                orphan,
                self.region,
                self.period,
            )
        for orphan in sorted(self.demand_orphans, key=lambda x: x[1]):
            logger.error(
                'Orphan process on demand side may cause erroneous results: %s in region %s, period %d',
                orphan,
                self.region,
                self.period,
            )

    def graph_network(self, temoa_config: TemoaConfig):
        # trial graphing...
        layers = {}
        for c in self.model_data.all_commodities:
            layers[c] = 2  # physical
        for c in self.model_data.source_commodities:
            layers[c] = 1
        # here we want to use this particular region-period to ID demands, as some commodities
        # may be producible, but *may* not be a demand in a particular region-period
        # if self.demand_commodities < self.M.commodity_demand:
        #     print(f'short commodities in period {self.period}/{self.region}')
        #     print(self.M.commodity_demand - self.demand_commodities)
        for c in self.model_data.demand_commodities[self.region, self.period]:
            layers[c] = 3
        edge_colors = {}
        edge_weights = {}
        for edge in self.demand_orphans:
            edge_colors[edge] = 'red'
            edge_weights[edge] = 5
        for edge in self.other_orphans:
            edge_colors[edge] = 'yellow'
            edge_weights[edge] = 3
        for edge in self.orig_connex:
            if edge[1] == '<<linked tech>>':
                edge_colors[edge] = 'blue'
                edge_weights[edge] = 3
        filename_label = f'{self.region}_{self.period}'
        graph_connections(
            self.orig_connex,
            layers,
            edge_colors,
            edge_weights,
            file_label=filename_label,
            output_path=temoa_config.output_path,
        )

    def unsupported_demands(self) -> set[str]:
        """
        Look for demand commodities that are not connected via a "good connection"
        :return: set of improperly supported demands
        """
        supported_demands = {t[2] for t in self.good_connections}
        bad_demands = {
            d
            for d in self.model_data.demand_commodities[self.region, self.period]
            if d not in supported_demands
        }
        return bad_demands


def _mark_good_connections(
    good_ic: set[str], connections: dict[str, set[tuple]], start: str | None = None
) -> set[tuple]:
    """
    Now that we have ID'ed the good ic that have been discovered, we need to work back up
    the chain of visited nodes to identify the good connections (this is the reverse of the
    previous search where we looked backward from demand.  Here we look up from the Input Commodities
    :param start: The current node to start from
    :param good_ic: The set of Input Commodities that were discovered by the first search
    :param connections:  The set of connections to analyze.  It is consumed by the function via pop()
    :return:
    """

    # end conditions...
    if not good_ic and not start:  # nothing to discover
        return set()
    else:
        good_connections = set()

    if not start:
        for start in good_ic:
            good_connections |= _mark_good_connections(good_ic, connections, start=start)

    # recurse...
    for oc, tech in connections.pop(start, []):  # prevent re-expanding this later by popping
        good_connections.add((start, tech, oc))
        # explore all upstream
        good_connections |= _mark_good_connections(
            good_ic=good_ic, connections=connections, start=oc
        )
    return good_connections


def _visited_dfs(
    start_nodes: set[str],
    end_nodes: set[str],
    connections: dict[str, set[tuple]],
    current_start=None,
) -> tuple[set, dict[str, set[tuple]]]:
    """
    recursive depth-first search to identify discovered source nodes and connections from
    a start point and set of connections
    :param start_nodes: the set of demand commodities (oc ∈ demand)
    :param end_nodes: source nodes, or ones traceable to source nodes
    :param connections: the connections to explore {output: {(ic, tech)}}
    :param current_start: the current node (ic) index
    :return: the set of viable tech tuples (ic, tech, oc)
    """
    # setup...
    discovered_sources = set()
    visited = defaultdict(set)

    # end conditions...
    if not current_start and not start_nodes:  # no more starts, we're done
        return set(), dict()
    if not current_start:  # start from each node in the starts
        for node in start_nodes:
            ds, v = _visited_dfs(
                start_nodes=start_nodes,
                end_nodes=end_nodes,
                connections=connections,
                current_start=node,
            )
            discovered_sources.update(ds)
            for k in v:
                visited[k].update(v[k])
        return discovered_sources, visited

    # we have a start node, dig from here.
    for ic, tech in connections.pop(current_start, []):  # we can pop, no need to re-explore
        visited[ic].add((current_start, tech))
        if ic in end_nodes:  # we have struck gold
            # add the current ic to discoveries
            discovered_sources.add(ic)
        else:
            # explore from here
            ds, v = _visited_dfs(
                start_nodes,
                end_nodes,
                connections,
                current_start=ic,
            )
            discovered_sources.update(ds)
            for k in v:
                visited[k].update(v[k])
    return discovered_sources, visited
