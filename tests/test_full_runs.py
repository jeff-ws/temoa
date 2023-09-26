"""
Test a couple full-runs to match objective function value and some internals
"""
import logging
import os
import pathlib
import shutil
import sqlite3

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
legacy_config_files = ['config_utopia', 'config_test_system', ]


@pytest.fixture(params=legacy_config_files)
def system_test_run(request):
    """
    spin up the model, solve it, and hand over the model and result for inspection
    """
    filename = request.param
    config_file = pathlib.Path(PROJECT_ROOT, 'tests', 'testing_configs', filename)
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
    assert pyo.value(res['Solution'][0]['Objective']['TotalCost']['Value']) == pytest.approx(
        expected_vals[TestVals.OBJ_VALUE], 0.00001)

    # inspect a couple set sizes
    efficiency_param: pyo.Param = mdl.Efficiency
    assert len(tuple(efficiency_param.sparse_iterkeys())) == expected_vals[
        TestVals.EFF_INDEX_SIZE], 'should match legacy numbers'
    assert len(efficiency_param._index) == expected_vals[TestVals.EFF_DOMAIN_SIZE], 'should match legacy numbers'


def test_myopic_utopia():
    """
    test the myopic functionality on Utopia.  We need to copy the source db to make the output and then erase
    it because re-runs with the same output db are not possible....get "UNIQUE" errors in db on 2nd run

    We will use the output target in the config file for this test as a shortcut to make/remove the database

    This test will change after conversion of temoa_myopic.py.  RN, it is a good placeholder

    """
    eps = 1e-3
    config_file = pathlib.Path(PROJECT_ROOT, 'tests', 'testing_configs', 'config_utopia_myopic')
    # config_file = pathlib.Path(PROJECT_ROOT, 'tests', 'testing_configs', 'config_utopia_myopic')
    input_db = pathlib.Path(PROJECT_ROOT, 'tests', 'testing_data', 'temoa_utopia.sqlite')
    output_db = pathlib.Path(PROJECT_ROOT, 'tests', 'testing_data', 'utopia_temp.sqlite')
    if os.path.isfile(output_db):
        os.remove(output_db)
    shutil.copy(input_db, output_db)  # put a new copy in place, ones that are used before fail.
    model = TemoaModel()
    temoa_solver = TemoaSolver(model, config_filename=config_file)
    for _ in temoa_solver.createAndSolve():
        pass
    # inspect the output db for results
    con = sqlite3.connect(output_db)
    cur = con.cursor()
    query = "SELECT t_periods, emissions FROM Output_Emissions WHERE tech is 'IMPDSL1'"
    emission = cur.execute(query).fetchall()

    # The emissions for diesel are present in each year and should be a good proxy for comparing
    # results
    diesel_emissions_by_year = {y: e for (y, e) in emission}
    assert abs(diesel_emissions_by_year[1990] - 2.8948) < eps
    assert abs(diesel_emissions_by_year[2000] - 2.4549) < eps
    assert abs(diesel_emissions_by_year[2010] - 5.4539) < eps
    os.remove(output_db)


