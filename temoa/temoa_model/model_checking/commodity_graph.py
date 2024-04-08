"""
A quick & dirty graph of the commodity network for troubleshooting purposes.  Future
development may enhance this quite a bit.... lots of opportunity!
"""

from pathlib import Path
from typing import Iterable

import gravis as gv
import networkx as nx

from temoa.temoa_model.model_checking.network_model_data import NetworkModelData, Tech
from temoa.temoa_model.temoa_config import TemoaConfig

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
Created on:  2/14/24

"""


def generate_graph(
    region,
    period,
    network_data: NetworkModelData,
    demand_orphans: Iterable[Tech],
    other_orphans: Iterable[Tech],
    driven_techs: Iterable[Tech],
    config: TemoaConfig,
):
    """
    generate graph for region/period from network data
    :param region: region of interest
    :param period: period of interest
    :param network_data: the data showing all edges to be graphed.  "orphans" will be added, if they aren't included
    :param demand_orphans: container of orphans [orphanage ;)]
    :param other_orphans: container of orphans
    :param driven_techs: the "driven" techs in LinkedTech pairs
    :param config:
    :return:
    """
    layers = {}
    for c in network_data.all_commodities:
        layers[c] = 2  # physical
    for c in network_data.source_commodities:
        layers[c] = 1
    for c in network_data.demand_commodities[region, period]:
        layers[c] = 3
    all_edges = set()
    edge_colors = {}
    edge_weights = {}
    # dev note:  the generators below do 2 things:  put the data in the format expected by the
    #            graphing code and reduce redundant vintages to 1 representation
    # we can ID all the possible driven techs and label them.  Note that if some of these are
    # orphans they will be overridden by those segments that follow

    for edge in ((tech.ic, tech.name, tech.oc) for tech in driven_techs):
        edge_colors[edge] = 'blue'
        edge_weights[edge] = 2
        all_edges.add(edge)
    for edge in ((tech.ic, tech.name, tech.oc) for tech in demand_orphans):
        edge_colors[edge] = 'red'
        edge_weights[edge] = 5
        all_edges.add(edge)
    for edge in ((tech.ic, tech.name, tech.oc) for tech in other_orphans):
        edge_colors[edge] = 'yellow'
        edge_weights[edge] = 3
        all_edges.add(edge)

    filename_label = f'{region}_{period}'
    # we pass in "all" of the techs for this region/period
    all_edges |= {
        (tech.ic, tech.name, tech.oc) for tech in network_data.available_techs[region, period]
    }
    _graph_connections(
        all_edges,
        layers,
        edge_colors,
        edge_weights,
        file_label=filename_label,
        output_path=config.output_path,
    )


def _graph_connections(
    connections: Iterable[tuple],
    layer_map,
    edge_colors,
    edge_weights,
    file_label: str,
    output_path: Path,
):
    """
    Make an HTML file containing the network graph
    :param connections: an iterable container of connections of format (input_comm, tech, output_comm)
    :param layer_map: An map of the layers.  1: source commodity, 2: physical commodity, 3: demand commodity
    :param edge_colors: color map of edges (technologies).  Non-entries default to black
    :param edge_weights: weight map of edges (technologies).  Non-entries default to 1.0
    :param file_label: the name of the output file
    :param output_path: the output directory
    :return:
    """
    dg = nx.DiGraph()  # networkx directed graph
    layer_colors = {1: 'limegreen', 2: 'violet', 3: 'darkorange'}
    node_size = {1: 50, 2: 15, 3: 30}
    for ic, tech, oc in connections:
        dg.add_node(
            ic,
            name=ic,
            layer=layer_map[ic],
            label=ic,
            color=layer_colors[layer_map[ic]],
            size=node_size[layer_map[ic]],
        )
        dg.add_node(
            oc,
            name=oc,
            layer=layer_map[oc],
            label=oc,
            color=layer_colors[layer_map[oc]],
            size=node_size[layer_map[oc]],
        )
        dg.add_edge(
            ic,
            oc,
            label=tech,
            color=edge_colors.get((ic, tech, oc), 'black'),
            size=edge_weights.get((ic, tech, oc), 1),
        )

    fig = gv.d3(
        dg,
        show_menu=True,
        show_node_label=True,
        node_label_data_source='label',
        show_edge_label=True,
        edge_label_data_source='label',
        edge_curvature=0.4,
        graph_height=1000,
        zoom_factor=1.0,
        node_drag_fix=True,
        node_label_size_factor=0.5,
        layout_algorithm_active=True,
    )
    filename = f'Commodity_Graph_{file_label}.html'
    output_path = output_path / filename
    fig.export_html(output_path, overwrite=True)


# quick test...  Not straight-forward on how to include this in unit tests...
if __name__ == '__main__':
    connex = [('ethos', 'tech_1', 2), (2, 'tech_2', 3)]
    layers = {'ethos': 1, 2: 2, 3: 3}
    _graph_connections(
        connex,
        layers,
        edge_colors={},
        edge_weights={},
        file_label='test_network_graph',
        output_path=Path('.'),
    )
