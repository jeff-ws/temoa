"""
utility to quickly capture db costs for a scenario for comparison
"""
from pathlib import Path

from definitions import PROJECT_ROOT

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
Created on:  2/27/24

"""

import json
import sqlite3

db_loc = Path(PROJECT_ROOT, 'tests', 'testing_outputs', 'temoa_test_system.sqlite')
json_loc = Path(PROJECT_ROOT, 'tests', 'testing_data', 'cost_vector_test_system.json')

con = sqlite3.connect(db_loc)
cur = con.cursor()
data = cur.execute(
    "SELECT regions, output_name, tech, vintage, output_cost FROM Output_Costs WHERE scenario = 'test_run'"
).fetchall()

with open(json_loc, 'w') as f_out:
    json.dump(data, f_out, indent=2)
