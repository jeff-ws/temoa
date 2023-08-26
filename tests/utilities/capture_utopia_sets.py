"""
Quick utility to capture set values from a pyomo model to enable later comparison.

This file should not need to be run again unless model schema changes
"""
# Written by:  J. F. Hyink
# jeff@westernspark.us
# https://westernspark.us
# Created on:  8/26/2023

import json
from os import path
import pyomo.environ as pyo

from definitions import PROJECT_ROOT
from src.temoa_model.temoa_model import TemoaModel
from src.temoa_model.temoa_run import TemoaSolver

output_file = path.join(PROJECT_ROOT, 'tests', 'testing_data', 'utopia_sets.json')
config_file = path.join(PROJECT_ROOT, 'tests', 'testing_configs', 'config_utopia_for_utility')

model = TemoaModel()
temoa_solver = TemoaSolver(model=model, config_filename=config_file)
# override the location of the .dat file in the config
temoa_solver.options
for _ in temoa_solver.createAndSolve():
    pass
instance_object = temoa_solver.instance_hook
model_sets = instance_object.instance.component_map(ctype=pyo.Set)
sets_dict = {k: list(v) for k, v in model_sets.items()}

# stash the result in a json file...
with open(output_file, 'w') as f_out:
    json.dump(sets_dict, f_out)
