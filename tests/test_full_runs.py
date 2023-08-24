"""
Test a couple full-runs to match objective function value and some internals
"""
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

# list of test scenarios for which we have captured results in legacy_test_values.py
legacy_config_files = ['config_utopia', 'config_test_system',] # 'config_utopia_myopic',]


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

