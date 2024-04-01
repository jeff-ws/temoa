"""
This module is used to verify that all demand commodities are traceable back to designated
source technologies
"""

from temoa.temoa_model.model_checking import network_model_data
from temoa.temoa_model.model_checking.commodity_graph import generate_graph
from temoa.temoa_model.model_checking.commodity_network import CommodityNetwork, logger
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
Created on:  2/3/24

"""


def source_trace(M: 'TemoaModel', temoa_config: TemoaConfig) -> bool:
    """
    trace the demand commodities back to designated source technologies
    :param temoa_config: the TemoaConfig instance
    :param M: the model to inspect
    :return: True if all demands are traceable, False otherwise
    """
    logger.debug('Starting source trace')
    demands_traceable = True
    for region in M.regions:
        for p in M.time_optimize:
            data = network_model_data.build(M)
            commodity_network = CommodityNetwork(region=region, period=p, model_data=data)
            commodity_network.analyze_network()
            if temoa_config.plot_commodity_network:
                generate_graph(
                    region,
                    p,
                    network_data=data,
                    demand_orphans=commodity_network.get_demand_side_orphans(),
                    other_orphans=commodity_network.get_other_orphans(),
                    driven_techs=data.get_driven_techs(region, p),
                    config=temoa_config,
                )
            unsupported_demands = commodity_network.unsupported_demands()
            if unsupported_demands:
                demands_traceable = False
                for commodity in unsupported_demands:
                    logger.error(
                        'Demand %s is not supported back to source commodities in region %s period %d',
                        commodity,
                        commodity_network.region,
                        commodity_network.period,
                    )
            if commodity_network.demand_orphans:
                demands_traceable = False
                # they are already logged...
    logger.debug('Completed source trace')
    return demands_traceable
