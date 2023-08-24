"""
a container for test values from legacy code (Python 3.7 / Pyomo 5.5) captured for continuity/development testing
"""
from enum import Enum

# Written by:  J. F. Hyink
# jeff@westernspark.us
# https://westernspark.us
# Created on:  6/27/23


class TestVals(Enum):
    OBJ_VALUE = 'obj_value'
    EFF_DOMAIN_SIZE = 'eff_domain_size'
    EFF_INDEX_SIZE = 'eff_index_size'


# these values were captured on base level runs of the .dat files in the tests/testing_data folder
test_vals = {'config_test_system': {TestVals.OBJ_VALUE: 491521.71997678,
                                    TestVals.EFF_DOMAIN_SIZE: 30720,
                                    TestVals.EFF_INDEX_SIZE: 74},
             'config_utopia': {TestVals.OBJ_VALUE: 36535.631200,
                               TestVals.EFF_DOMAIN_SIZE: 12312,
                               TestVals.EFF_INDEX_SIZE: 64},
             'config_utopia_myopic': {TestVals.OBJ_VALUE: 0.0,
                                      TestVals.EFF_DOMAIN_SIZE: 0,
                                      TestVals.EFF_INDEX_SIZE: 0
                                    }}

