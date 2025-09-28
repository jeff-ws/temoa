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
Created on:  9/19/25

common elements used within Unit Checking

"""
from dataclasses import dataclass

tables_with_units = [
    'CapacityToActivity',
    'Commodity',
    'CostEmission',
    'CostFixed',
    'CostInvest',
    'CostVariable',
    'Demand',
    'Efficiency',
    'EmissionActivity',
    'EmissionLimit',
    'ExistingCapacity',
    'GrowthRateSeed',
    'LifetimeProcess',
    'LifetimeTech',
    'LoanLifetimeTech',
    'MaxActivity',
    'MaxActivityGroup',
    'MaxCapacity',
    'MaxCapacityGroup',
    'MaxNewCapacity',
    'MaxNewCapacityGroup',
    'MaxResource',
    'MinActivity',
    'MinActivityGroup',
    'MinCapacity',
    'MinCapacityGroup',
    'MinNewCapacity',
    'MinNewCapacityGroup',
    'OutputBuiltCapacity',
    'OutputCost',
    'OutputCurtailment',
    'OutputEmission',
    'OutputFlowIn',
    'OutputFlowOut',
    'OutputNetCapacity',
    'OutputObjective',
    'OutputRetiredCapacity',
    'StorageDuration',
]
"""Tables that have units"""

ratio_capture_tables = {
    'Efficiency',
    # 'EmissionActivity',
    # 'CostEmission',
    # 'CostFixed',
    # 'CostInvest',
    # 'CostVariable',
}
"""Tables that require ratio capture in form "units / (other units)" """

commodity_based_tables = [
    'Demand',
    'MaxResource',  # haven't we done away with this table/constraint?
]
activity_based_tables = [
    'MaxActivity',
    # 'MaxActivityGroup',
    'MinActivity',
    # 'MinActivityGroup',
]
"""Tables that should have units equivalent to the commodity's native units"""

capacity_based_tables = [
    'ExistingCapacity',
    'MaxCapacity',
    # 'MaxCapacityGroup',
    'MaxNewCapacity',
    # 'MaxNewCapacityGroup',
    'MinCapacity',
    # 'MinCapacityGroup',
    'MinNewCapacity',
    # 'MinNewCapacityGroup',
]
"""Tables that require conversion via CapacityToActivity to reach the native units"""

per_capacity_based_tables = [
    'CostFixed',
    'CostInvest',
]
"""tables with capacity in the denominator"""

period_based_tables = [
    'LifetimeProcess',
    'LifetimeTech',
    'LoanLifetimeTech',
]
"""Tables that align to the time period, presumably 'years'"""

# we need to delineate whether the units are commodity-referenced or tech-referenced and if they are "capacity based" so...
# format:  (table_name, commodity field name (None if 'tech' based), capacity based )
cost_based_tables = [
    ('CostEmission', 'emis_comm', False),
    ('CostFixed', None, True),
    ('CostInvest', None, True),
    ('CostVariable', None, False),
]
"""Tables that have cost units"""


# TODO:  Unclear tables:  MaxResource, GrowthRateSeed


@dataclass(frozen=True)
class UnitsFormat:
    format: str
    groups: int


# any gathering of letters and allowed symbols which are "*" and "_" with end lead/trail spaces trimmed
SINGLE_ELEMENT = UnitsFormat(format=r'^\s*([A-Za-z0-9\*\^\_\s\/\(\)]+?)\s*$', groups=1)

# any fractional expression using the same pattern above with the denominator IN PARENTHESES
RATIO_ELEMENT = UnitsFormat(
    format=r'^\s*([A-Za-z0-9\*\/\^\_\s]+?)\s*\/\s*\(\s*([A-Za-z0-9\*\^\/\(\)\_\s]+?)\s*\)\s*$',
    groups=2,
)
"""Format for a units ratio.  re will return the first group as the numerator and the second as the denominator"""

ACCEPTABLE_CHARACTERS = r'^\s*([A-Za-z0-9\*\^\_\s\/\(\)]+?)\s*$'


def consolidate_lines(line_nums: list[str | int]) -> list[str]:
    listed_lines = (
        line_nums
        if len(line_nums) < 5
        else f'{", ".join(str(t) for t in line_nums[:5])}", ... +{len(line_nums)-5} more"'
    )
    return listed_lines
