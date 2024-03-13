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
from logging import getLogger
from typing import Iterable

from temoa.temoa_model.model_checking.commodity_graph import graph_connections
from temoa.temoa_model.model_checking.commodity_network import CommodityNetwork
from temoa.temoa_model.model_checking.network_model_data import NetworkModelData, Tech
from temoa.temoa_model.temoa_config import TemoaConfig

logger = getLogger(__name__)


class CommodityNetworkManager:
    """Manager to run the network analysis recursively for a region and set of periods"""

    def __init__(self, periods: Iterable[str | int], network_data: NetworkModelData):
        self.regions = None
        self.analyzed = False
        self.periods = sorted(periods)
        self.data = network_data

        # outputs / saves for graphing networks
        # orig_tech is saved copy of the links for graphing purposes
        # this is a quick "deep copy"
        self.orig_tech = {k: v.copy() for k, v in network_data.available_techs.items()}
        self.demand_orphans: dict[tuple[str, str], set[Tech]] = defaultdict(set)
        self.other_orphans: dict[tuple[str, str], set[Tech]] = defaultdict(set)
        self.valid_synthetic_links: dict[tuple[str, str], set[Tech]] = defaultdict(set)

    def _analyze_region(self, region: str):
        """recursively whittle away at the region, within the window until no new invalid techs appear"""
        done = False
        iter_count = 0

        while not done:
            iter_count += 1
            demand_orphans_this_pass: set[Tech] = set()
            other_orphans_this_pass: set[Tech] = set()
            for period in self.periods:
                cn = CommodityNetwork(region=region, period=period, model_data=self.data)
                cn.analyze_network()

                # gather orphans...
                new_demand_orphans = cn.get_demand_side_orphans()
                new_other_orphans = cn.get_other_orphans()

                # add the orphans to the orphanages...
                self.demand_orphans[region, period] |= new_demand_orphans
                self.other_orphans[region, period] |= new_other_orphans

                # add them to the collections for the "pass"
                demand_orphans_this_pass |= new_demand_orphans
                other_orphans_this_pass |= new_other_orphans

                # we want to capture the synthetic links on the last pass, so do it each time
                # and just capture it (don't add)
                self.valid_synthetic_links[region, period] = cn.get_synthetic_links()

            # clean up the good tech listing and decide whether to go again...
            # dev note:  we could clean up the good techs in the loop, before processing next period, but
            #            by doing it this way, we properly capture full set of orphans by period/region
            #            for later use
            for period in self.periods:
                # any orphans need to be removed from all periods where they exist
                self.data.available_techs[region, period] -= demand_orphans_this_pass
                self.data.available_techs[region, period] -= other_orphans_this_pass

            done = not demand_orphans_this_pass and not other_orphans_this_pass
            logger.debug(
                'Finished %s pass(es) on region %s during removal of orphan techs',
                iter_count,
                region,
            )
            logger.debug(
                'Removed %d orphans', len(demand_orphans_this_pass) + len(other_orphans_this_pass)
            )
            for orphan in sorted(demand_orphans_this_pass):
                logger.warning('Removed %s as demand-side orphan', orphan)
            for orphan in sorted(other_orphans_this_pass):
                logger.warning('Removed %s as other orphan', orphan)

    def analyze_network(self):
        """
        Analyze all regions in the model, excluding exchanges
        :return:
        """
        # NOTE:  by excluding '-' regions, we are deciding NOT to screen any regional exchange techs,
        #        which would be a whole different level of difficulty to do.
        self.regions = {r for (r, p) in self.data.available_techs if '-' not in r}
        for region in self.regions:
            logger.debug('starting network analysis for region %s', region)
            self._analyze_region(region)
        self.analyzed = True

    def build_filters(self) -> dict:
        """populate the filters from the data, after network analysis"""
        if not self.analyzed:
            raise RuntimeError('Trying to build filters before network analysis.  Code error')
        valid_ritvo = set()
        valid_rtv = set()
        valid_rt = set()
        valid_t = set()
        valid_input_commodities = set()
        valid_output_commodities = set()
        valid_vintages = set()
        for r, p in self.data.available_techs:
            for tech in self.data.available_techs[r, p]:
                valid_ritvo.add((tech.region, tech.ic, tech.name, tech.vintage, tech.oc))
                valid_rtv.add((tech.region, tech.name, tech.vintage))
                valid_rt.add((tech.region, tech.name))
                valid_t.add(tech.name)
                valid_input_commodities.add(tech.ic)
                valid_output_commodities.add(tech.oc)
                valid_vintages.add(tech.vintage)
        filts = {
            'ritvo': valid_ritvo,
            'rtv': valid_rtv,
            'rt': valid_rt,
            't': valid_t,
            'v': valid_vintages,
            'ic': valid_input_commodities,
            'oc': valid_output_commodities,
        }
        return filts

    def make_commodity_plots(self, config: TemoaConfig):
        if not self.analyzed:
            raise RuntimeError('Trying to build graphs before network analysis.  Code error')
        for region in self.regions:
            for period in self.periods:
                layers = {}
                for c in self.data.all_commodities:
                    layers[c] = 2  # physical
                for c in self.data.source_commodities:
                    layers[c] = 1
                for c in self.data.demand_commodities[region, period]:
                    layers[c] = 3

                edge_colors = {}
                edge_weights = {}
                # dev note:  the generators below do 2 things:  put the data in the format expected by the
                #            graphing code and reduce redundant vintages to 1 representation
                for edge in (
                    (tech.ic, tech.name, tech.oc) for tech in self.demand_orphans[region, period]
                ):
                    edge_colors[edge] = 'red'
                    edge_weights[edge] = 5
                for edge in (
                    (tech.ic, tech.name, tech.oc) for tech in self.other_orphans[region, period]
                ):
                    edge_colors[edge] = 'yellow'
                    edge_weights[edge] = 3
                valid_synthetic_links = {
                    (tech.ic, tech.name, tech.oc)
                    for tech in self.valid_synthetic_links[region, period]
                }
                for edge in valid_synthetic_links:
                    edge_colors[edge] = 'blue'
                    edge_weights[edge] = 3
                filename_label = f'{region}_{period}'
                # we pass in "all" of the techs for this region/period and know that the above decorations are
                # a subset of all available techs that we started with
                all_links = {
                    (tech.ic, tech.name, tech.oc) for tech in self.orig_tech[region, period]
                } | valid_synthetic_links
                graph_connections(
                    all_links,
                    layers,
                    edge_colors,
                    edge_weights,
                    file_label=filename_label,
                    output_path=config.output_path,
                )
