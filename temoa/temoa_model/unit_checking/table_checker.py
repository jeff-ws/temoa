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

functions to check tables within a version 3.1 database for units compliance

"""
import logging
import re
import sqlite3

from pint.registry import Unit

from temoa.temoa_model.unit_checking import ureg
from temoa.temoa_model.unit_checking.common import (
    ratio_capture_tables,
    RATIO_ELEMENT,
    SINGLE_ELEMENT,
    ACCEPTABLE_CHARACTERS,
    consolidate_lines,
    capacity_based_tables,
)
from temoa.temoa_model.unit_checking.entry_checker import (
    validate_units_expression,
    validate_units_format,
    gather_from_table,
)

logger = logging.getLogger(__name__)


def check_table(conn: sqlite3.Connection, table_name: str) -> tuple[dict[str, Unit], list[str]]:
    """
    Check all entries in a table for format and registry compliance
    This "first pass" gathers common entries for efficiency"""
    errors = []
    res = {}
    format_type = RATIO_ELEMENT if table_name in ratio_capture_tables else SINGLE_ELEMENT

    # this function gathers all unique entries by row number for efficiency in larger tables
    entries = gather_from_table(conn, table_name)
    for expr, line_nums in entries.items():
        # mark the blanks
        if not expr:
            listed_lines = consolidate_lines(line_nums)
            errors.append(f'Blank units entry found at rows: {listed_lines}')
            continue

        # check characters
        valid_chars = re.search(ACCEPTABLE_CHARACTERS, expr)
        if not valid_chars:
            listed_lines = consolidate_lines(line_nums)
            errors.append(
                f'Invalid character(s): {expr if expr else "<no recognized entry>"} [only letters, underscore '
                f'and "*, /, ^, ()" operators allowed] at rows: {listed_lines}  '
            )
            continue

        # Check format
        valid, elements = validate_units_format(expr, format_type)
        if not valid:
            listed_lines = consolidate_lines(line_nums)
            if format_type == RATIO_ELEMENT:
                msg = (
                    f'Format violation at rows.  {listed_lines}:  {expr}.  '
                    f'Check illegal chars/operators and that denominator is isolated in parentheses.'
                )
            else:
                msg = (
                    f'Format violation at rows.  {listed_lines}:  {expr}.  '
                    f'Check for illegal characters or operators.'
                )

            errors.append(msg)
            continue

        # Check registry compliance
        converted_units = []
        for element in elements:
            if element:
                success, units = validate_units_expression(element)
                if not success:
                    listed_lines = consolidate_lines(line_nums)
                    errors.append(
                        f'Registry violation (UNK units): {element} at rows: {listed_lines}'
                    )
                else:
                    converted_units.append(units)
        if len(converted_units) != format_type.groups:
            # we came up short of something, skip this entry
            continue

        # if we have a relationship with "capacity" check that we have some time units
        # this test is disabled for RATIO_ELEMENT based tables due to ambiguities
        if table_name in capacity_based_tables and format_type == SINGLE_ELEMENT:
            test_value = converted_units[0]
            # test if compatible with standard "power" units (magnitude doesn't matter)
            capacity_like = ureg.watt in test_value.compatible_units()
            if not capacity_like:
                # test for time units in denominator as backup test
                capacity_like = test_value.dimensionality.get('[time]') != -1

            if not capacity_like:
                listed_lines = consolidate_lines(line_nums)
                errors.append(
                    f'Time dimension of capacity entry: {expr} *might* be missing in denominator '
                    f'or this may not be a standard "power" expression:  {listed_lines}'
                )

        # assemble a reference of item: units-relationship if we have a valid entry
        if len(converted_units) == format_type.groups:  # we have the right number
            if format_type == SINGLE_ELEMENT:
                ref = {expr: converted_units[0]}
                res.update(ref)
            elif format_type == RATIO_ELEMENT:
                ref = {expr: converted_units[0] / converted_units[1]}
                res.update(ref)
            else:
                raise ValueError('Unknown units format: %s', format_type)
    return res, errors
