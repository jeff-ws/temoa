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
Created on:  9/22/25

Set of tests for related to the unit checker

"""
import pytest

from temoa.temoa_model.unit_checking import ureg
from temoa.temoa_model.unit_checking.common import SINGLE_ELEMENT, RATIO_ELEMENT
from temoa.temoa_model.unit_checking.entry_checker import (
    validate_units_format,
    validate_units_expression,
)

cases = [
    ('PJ', SINGLE_ELEMENT, True),
    ('   kWh', SINGLE_ELEMENT, True),
    ('dog_food   ', SINGLE_ELEMENT, True),
    ('  G * tonne', SINGLE_ELEMENT, True),
    ('Mt.steel ', SINGLE_ELEMENT, False),  # period not allowed
    ('PJ / day', SINGLE_ELEMENT, False),  # no slash char
    ('PJ    / (kT)', RATIO_ELEMENT, True),
    ('(PJ) / (kT)', RATIO_ELEMENT, True),  # numerator optionally parenthesized
    ('PJ / kT', RATIO_ELEMENT, False),  # no parens on denom
    ('kWh/day/(cycle)', RATIO_ELEMENT, False),  # no slash char
]


@pytest.mark.parametrize(
    'entry, units_format, expected',
    cases,
    ids=[f"{t[0]} -> {'valid' if t[2] else 'invalid'}" for t in cases],
)
def test_format_validation(entry, units_format, expected):
    """Test the regex matching for unit format
    Note:  The unit values here are NOT tested within the Units Registry
    This test is solely to test the regex to grab the units, esp the ratio units"""
    assert validate_units_format(expr=entry, unit_format=units_format)


cases = [
    ('kg', (True, ureg.kg)),
    ('kg/m^3', (True, ureg('kg/(meter*meter*meter)'))),
    ('m/s', (True, ureg('m/s'))),
    ('dog_food', (False, None)),
    ('ethos', (True, ureg.ethos)),
    ('passenger', (True, ureg.passenger)),
    ('seat', (True, ureg.seat)),
    ('dollar', (True, ureg.dollar)),
    ('dollars', (True, ureg.dollar)),
    ('USD', (True, ureg.dollar)),
    ('EUR', (True, ureg.euro)),
    ('kWh', (True, ureg.kWh)),
]


@pytest.mark.parametrize(
    'expr, expected_result',
    cases,
    ids=[f"{t[0]} -> {'valid' if t[1][0]else 'invalid'}" for t in cases],
)
def test_validate_units_expression(expr, expected_result):
    """
    Test the validate_units_expression function against various unit expressions.
    """
    result = validate_units_expression(expr)
    assert result == expected_result


cases = [('kW', -3), ('kWh', -2), ('PJ', -2), ('PJ/h', -3)]


@pytest.mark.parametrize('expr, location', cases, ids=[t[0] for t in cases])
def test_time_dimenstion_locator(expr, location: int):
    test_value = validate_units_expression(expr)[1]
    found = test_value.dimensionality.get('[time]')
    assert (
        found == location
    ), f'time dimension not found at expected location for units: {test_value}'
