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

from unittest.mock import MagicMock

import pytest

from temoa.temoa_model.model_checking import network_model_data
from temoa.temoa_model.model_checking.source_check import CommodityNetwork


# let's model this faulty network as a trial:

#     - t4(2) -> p3
#   /
# s1 -> t1 -> p1 -> t2 -> d1
#                        /
#             p2 -> t3  -
#
#             p2 -> t5 -> d2

# the above should produce:
# 2 valid techs, t1, t2
# 2 supply-side orphans (both instances of t4 of differing vintage)
# 1 demand-side orpha: t3


# we need a small fixture to simulate the database here
@pytest.fixture
def mock_db_connection():
    data = [
        [(t,) for t in ['s1', 'p1', 'p2', 'p3', 'd1']],  # all commodities
        [
            (t,)
            for t in [
                's1',
            ]
        ],  # sources
        [('R1', 2020, 'd1'), ('R1', 2020, 'd2')],  # demands
        [
            ('R1', 's1', 't4', 2000, 'p3', 100),
            ('R1', 's1', 't4', 1990, 'p3', 100),
            ('R1', 's1', 't1', 2000, 'p1', 100),
            ('R1', 'p1', 't2', 2000, 'd1', 100),
            ('R1', 'p2', 't3', 2000, 'd1', 100),
            ('R1', 'p2', 't5', 2000, 'd2', 100),
        ],  # techs
        [(2020,)],  # periods
        [],  # no linked techs
    ]

    mock_con = MagicMock()
    mock_cursor = MagicMock()
    mock_con.cursor.return_value = mock_cursor
    mock_execute = MagicMock()
    mock_cursor.execute.return_value = mock_execute
    mock_execute.fetchall.side_effect = data
    return mock_con


def test__build_from_db(mock_db_connection):
    network_data = network_model_data._build_from_db(mock_db_connection)
    assert len(network_data.demand_commodities) == 1, 'only 1 demand'
    assert len(network_data.available_techs['R1', 2020]) == 6, '6 techs are available'


def test_source_trace(mock_db_connection):
    network_data = network_model_data._build_from_db(mock_db_connection)
    cn = CommodityNetwork(region='R1', period=2020, model_data=network_data)
    cn.analyze_network()

    # test the outputs
    assert len(cn.get_valid_tech()) == 2
    assert len(cn.get_demand_side_orphans()) == 2
    assert len(cn.get_other_orphans()) == 2
    assert 'd2' in cn.unsupported_demands(), 'd2 has no techs driving it'
