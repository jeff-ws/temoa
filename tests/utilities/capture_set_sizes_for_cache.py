"""
Utility to capture the set sizes for inspection/comparison

Written by:  J. F. Hyink
jeff@westernspark.us
https://westernspark.us
Created on:  11/14/23

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

import json
import logging
import sys
from pathlib import Path

import pyomo.environ as pyo

from definitions import PROJECT_ROOT
from temoa.temoa_model.temoa_sequencer import TemoaSequencer

logger = logging.getLogger(__name__)

print(
    'WARNING:  Continuing to execute this file will update the cached values for the set sizes for US_9R model in '
    'the testing_data folder from the sqlite databases in the same folder.  This should only need to be done if the '
    'schema or model have changed and that database has been updated.'
)

t = input('Type "Y" to continue, any other key to exit now.')
if t not in {'y', 'Y'}:
    sys.exit(0)
output_file = Path(PROJECT_ROOT, 'tests', 'testing_data', 'US_9R_8D_set_sizes.json')
config_file = Path(PROJECT_ROOT, 'tests', 'utilities', 'config_US_9R_8D.toml')
options = {'silent': True, 'debug': True}
sequencer = TemoaSequencer(
    config_file=config_file, output_path=Path(PROJECT_ROOT, 'tests', 'testing_log'), **options
)
instance = sequencer.start()

model_sets = instance.component_map(ctype=pyo.Set)
sets_dict = {k: len(v) for k, v in model_sets.items() if '_index' not in k}

# stash the result in a json file...
with open(output_file, 'w') as f_out:
    json.dump(sets_dict, f_out, indent=2)


# chunk below is temp storage of "old version" that was used to pluck set values before the reconfiguration
# of the run.  Delete later

# from temoa.temoa_model.temoa_run import TemoaSolver
#
# print("WARNING:  Continuing to execute this file will update the cached values for the set sizes for US_9R model in "
#       "the testing_data folder from the sqlite databases in the same folder.  This should only need to be done if the "
#       "schema or model have changed and that database has been updated.")
#
# t = input('Type "Y" to continue, any other key to exit now.')
# if t not in {'y', 'Y'}:
#     sys.exit(0)
# output_file = path.join(PROJECT_ROOT, 'tests', 'testing_data', 'US_9R_set_sizes.json')
# config_file = path.join(PROJECT_ROOT, 'tests', 'utilities', 'config_US_9R_for_utility')
#
# model = TemoaModel('utility')
# temoa_solver = TemoaSolver(model=model, config_filename=config_file)
#
# # TODO:  This relies on the solve mechanism to be hard-coded to skip the solve
# #        update after a better sequencer is developed
# for _ in temoa_solver.createAndSolve():
#     pass
# instance_object = temoa_solver.instance_hook
# model_sets = instance_object.instance.component_map(ctype=pyo.Set)
# sets_dict = {k: len(v) for k, v in model_sets.items()}
#
# # stash the result in a json file...
# with open(output_file, 'w') as f_out:
#     json.dump(sets_dict, f_out, indent=2)
