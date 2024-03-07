"""
pytest configuration

Written by:  J. F. Hyink
jeff@westernspark.us
https://westernspark.us
Created on:  6/27/23

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

import logging
import os
import pathlib
import shutil
from typing import Any

import pytest
from pyomo.opt import SolverResults

from definitions import PROJECT_ROOT
from temoa.temoa_model.temoa_model import TemoaModel
from temoa.temoa_model.temoa_sequencer import TemoaSequencer

logger = logging.getLogger(__name__)

# set the target folder for output from testing
output_path = os.path.join(PROJECT_ROOT, 'tests', 'testing_log')
if not os.path.exists(output_path):
    os.mkdir(output_path)

# set up logger in conftest.py so that it is properly anchored in the test folder.
filename = 'testing.log'
logging.basicConfig(
    filename=os.path.join(output_path, filename),
    filemode='w',
    format='%(asctime)s | %(module)s | %(levelname)s | %(message)s',
    datefmt='%d-%b-%y %H:%M:%S',
    level=logging.DEBUG,  # <-- global change for testing activities is here
)

logging.getLogger('pyomo').setLevel(logging.WARNING)
logging.getLogger('matplotlib').setLevel(logging.WARNING)
logging.getLogger('pyutilib').setLevel(logging.WARNING)

# ensure that dummy copies of utopia and test_system databases are available in testing_outputs
# to catch data.  These are just sumps to absorb non-inspected output to keep the input sources "pristine"
data_output_path = os.path.join(PROJECT_ROOT, 'tests', 'testing_outputs')
data_source_path = os.path.join(PROJECT_ROOT, 'tests', 'testing_data')
databases = (
    'temoa_utopia.sqlite',
    'temoa_test_system.sqlite',
    'storageville.sqlite',
    'mediumville.sqlite',
)
for db in databases:
    if not os.path.exists(os.path.join(data_output_path, db)):
        shutil.copy(os.path.join(data_source_path, db), os.path.join(data_output_path, db))


# make a fresh copy of utopia for myopic use, when called for
def copy_utopia_for_myopic():
    logger.debug('Making a copy of utopia for testing')
    shutil.copy(
        os.path.join(data_source_path, 'temoa_utopia.sqlite'),
        os.path.join(data_output_path, 'myo_temoa_utopia.sqlite'),
    )


@pytest.fixture()
def system_test_run(
    request, tmp_path
) -> tuple[Any, SolverResults | None, TemoaModel | None, TemoaSequencer]:
    """
    spin up the model, solve it, and hand over the model and result for inspection
    """
    data_name = request.param['name']
    logger.info('Setting up and solving: %s', data_name)
    if data_name == 'myopic utopia':
        copy_utopia_for_myopic()
    filename = request.param['filename']
    options = {'silent': True, 'debug': True}
    config_file = pathlib.Path(PROJECT_ROOT, 'tests', 'testing_configs', filename)

    sequencer = TemoaSequencer(
        config_file=config_file,
        output_path=tmp_path,
        **options,
    )
    sequencer.start()
    res = sequencer.pf_results
    mdl = sequencer.pf_solved_instance
    return data_name, res, mdl, sequencer
