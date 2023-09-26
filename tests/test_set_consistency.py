"""
These tests are designed to check the construction of the numerous sets in the 2 exemplar models:
Utopia and Test System.

They construct all the pyomo Sets associated with the model and compare them with cached results that are stored
in json files
"""


# Written by:  J. F. Hyink
# jeff@westernspark.us
# https://westernspark.us
# Created on:  9/26/23

import json
import pathlib

from pyomo import environ as pyo

from definitions import PROJECT_ROOT
from src.temoa_model.temoa_model import TemoaModel
from src.temoa_model.temoa_run import TemoaSolver


def test_upoptia_set_consistency():
    """
    test the set membership of the utopia model against cached values to ensure consistency
    """
    config_file = pathlib.Path(PROJECT_ROOT, 'tests', 'testing_configs', 'config_utopia')
    model = TemoaModel()
    temoa_solver = TemoaSolver(model=model, config_filename=config_file)
    for _ in temoa_solver.createAndSolve():
        pass

    # capture the sets within the model
    model_sets = temoa_solver.instance_hook.instance.component_map(ctype=pyo.Set)
    model_sets = {k: set(v) for k, v in model_sets.items()}

    # retrieve the cache and convert the set values from list -> set (json can't store sets)
    cache_file = pathlib.Path(PROJECT_ROOT, 'tests', 'testing_data', 'utopia_sets.json')
    with open(cache_file, 'r') as src:
        cached_sets = json.load(src)
    cached_sets = {k: set(tuple(t) if isinstance(t, list) else t for t in v) for (k, v) in cached_sets.items()}

    assert model_sets == cached_sets, 'The utopia run-produced sets did not match cached values'


def test_test_system_set_consistency():
    """
    Test the set membership of the Test System model against cache.
    """
    # this could be combined with the similar test for utopia to use the fixture at some time...
    config_file = pathlib.Path(PROJECT_ROOT, 'tests', 'testing_configs', 'config_test_system')
    model = TemoaModel()
    temoa_solver = TemoaSolver(model=model, config_filename=config_file)
    for _ in temoa_solver.createAndSolve():
        pass
    model_sets = temoa_solver.instance_hook.instance.component_map(ctype=pyo.Set)
    model_sets = {k: set(v) for k, v in model_sets.items()}

    cache_file = pathlib.Path(PROJECT_ROOT, 'tests', 'testing_data', 'test_system_sets.json')
    with open(cache_file, 'r') as src:
        cached_sets = json.load(src)
    cached_sets = {k: set(tuple(t) if isinstance(t, list) else t for t in v) for (k, v) in cached_sets.items()}

    assert model_sets == cached_sets, 'The Test System run-produced sets did not match cached values'
