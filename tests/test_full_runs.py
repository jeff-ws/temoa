"""
Test a couple full-runs to match objective function value and some internals
"""
import json
import logging
import os

import pyomo.environ as pyo
import pytest

from definitions import PROJECT_ROOT
# from src.temoa_model.temoa_model import temoa_create_model
from src.temoa_model.temoa_model import TemoaModel
from src.temoa_model.temoa_run import TemoaSolver
from tests.legacy_test_values import TestVals, test_vals

# Written by:  J. F. Hyink
# jeff@westernspark.us
# https://westernspark.us
# Created on:  6/27/23


logger = logging.getLogger(__name__)
# list of test scenarios for which we have captured results in legacy_test_values.py
legacy_config_files = ['config_utopia', 'config_test_system', 'config_utopia_myopic',]


@pytest.fixture(params=legacy_config_files)
def system_test_run(request):
    """
    spin up the model, solve it, and hand over the model and result for inspection
    """
    filename = request.param
    config_file = os.path.join(PROJECT_ROOT, 'tests', 'testing_configs', filename)
    # make a TemoaSolver and pass it a model instance and the config file
    model = TemoaModel()
    temoa_solver = TemoaSolver(model, config_filename=config_file)
    for _ in temoa_solver.createAndSolve():
        pass

    instance_object = temoa_solver.instance_hook
    res = instance_object.result
    mdl = instance_object.instance
    return filename, res, mdl


def test_against_legacy_outputs(system_test_run):
    """
    This test compares tests of legacy models to captured test results
    """
    filename, res, mdl = system_test_run
    logger.info("Starting output test on scenario: %s", filename)
    expected_vals = test_vals.get(filename)  # a dictionary of expected results

    # inspect some summary results
    assert pyo.value(res['Solution'][0]['Status'].key) == 'optimal'
    assert pyo.value(res['Solution'][0]['Objective']['TotalCost']['Value']) == \
           pytest.approx(expected_vals[TestVals.OBJ_VALUE], 0.00001)

    # inspect a couple set sizes
    efficiency_param: pyo.Param = mdl.Efficiency
    assert len(tuple(efficiency_param.sparse_iterkeys())) == expected_vals[
        TestVals.EFF_INDEX_SIZE], 'should match legacy numbers'
    assert len(efficiency_param._index) == expected_vals[TestVals.EFF_DOMAIN_SIZE], 'should match legacy numbers'

def test_upoptia_set_consistency():
    """
    test the set membership of the utopia model against cached values to ensure consistency
    """
    config_file = os.path.join(PROJECT_ROOT, 'tests', 'testing_configs', 'config_utopia')
    model = TemoaModel()
    temoa_solver = TemoaSolver(model=model, config_filename=config_file)
    for _ in temoa_solver.createAndSolve():
        pass

    # capture the sets within the model
    model_sets = temoa_solver.instance_hook.instance.component_map(ctype=pyo.Set)
    model_sets = {k: set(v) for k, v in model_sets.items()}

    # retrieve the cache and convert the set values from list -> set (json can't store sets)
    cache_file = os.path.join(PROJECT_ROOT, 'tests', 'testing_data', 'utopia_sets.json')
    with open(cache_file, 'r') as src:
        cached_sets = json.load(src)
    # print(cached_sets)
    cached_sets = {k: set(tuple(t) if isinstance(t, list) else t for t in v) for (k, v) in cached_sets.items()}

    assert model_sets == cached_sets, 'The utopia run-produced sets did not match cached values'

def test_test_system_set_consistency():
    """
    Test the set membership of the Test System model against cache.
    """
    # this could be combined with the similar test for utopia to use the fixture at some time...
    config_file = os.path.join(PROJECT_ROOT, 'tests', 'testing_configs', 'config_test_system')
    model = TemoaModel()
    temoa_solver = TemoaSolver(model=model, config_filename=config_file)
    for _ in temoa_solver.createAndSolve():
        pass
    model_sets = temoa_solver.instance_hook.instance.component_map(ctype=pyo.Set)
    model_sets = {k: set(v) for k, v in model_sets.items()}

    cache_file = os.path.join(PROJECT_ROOT, 'tests', 'testing_data', 'test_system_sets.json')
    with open(cache_file, 'r') as src:
        cached_sets = json.load(src)
    cached_sets = {k: set(tuple(t) if isinstance(t, list) else t for t in v) for (k, v) in cached_sets.items()}

    assert model_sets == cached_sets, 'The Test System run-produced sets did not match cached values'