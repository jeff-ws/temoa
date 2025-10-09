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
from pathlib import Path

from pint.registry import Unit

from temoa.temoa_model.unit_checking.common import (
    tables_with_units,
    ratio_capture_tables,
    RATIO_ELEMENT,
    SINGLE_ELEMENT,
    ACCEPTABLE_CHARACTERS,
    consolidate_lines,
    capacity_based_tables,
    per_capacity_based_tables,
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
    This "first pass" gathers common entriesfor efficiency"""
    errors = []
    res = {}
    format_type = RATIO_ELEMENT if table_name in ratio_capture_tables else SINGLE_ELEMENT

    # check for incompatible screens...
    if table_name in capacity_based_tables:
        if format_type == RATIO_ELEMENT:
            logger.warning('Checking of RATIO_ELEMENTs for capacity-type units is NOT implemented')

    entries = gather_from_table(conn, table_name)
    for expr, line_nums in entries.items():
        # check characters
        valid_chars = re.search(ACCEPTABLE_CHARACTERS, expr)
        if not valid_chars:
            listed_lines = consolidate_lines(line_nums)

            errors.append(
                f'  Invalid character(s) at rows {listed_lines} [only letters, underscore and "*, /, ^, ()" operators allowed]: {expr if expr else "<no recognized entry>"}'
            )
            continue

        # Check format
        valid, elements = validate_units_format(expr, format_type)
        if not valid:
            listed_lines = consolidate_lines(line_nums)

            errors.append(f'  Format violation at rows {listed_lines}:  {expr}')
            continue

        # Check registry compliance
        converted_units = []
        for element in elements:
            if element:
                success, units = validate_units_expression(element)
                if not success:
                    listed_lines = consolidate_lines(line_nums)
                    errors.append(
                        f'  Registry violation (UNK units) at rows {listed_lines}:  {element}'
                    )
                else:
                    converted_units.append(units)

        # if we have a relationship with "capacity" check that we have some time units
        if table_name in capacity_based_tables and format_type == SINGLE_ELEMENT:
            test_value = converted_units[0]
            if test_value.dimensionality.get('[time]') != -1:
                # no time in numerator
                listed_lines = consolidate_lines(line_nums)
                errors.append(
                    f'  No time dimension in denominator of capacity entry at rows {listed_lines}:  {expr}'
                )
        if table_name in per_capacity_based_tables and format_type == SINGLE_ELEMENT:
            test_value = converted_units[0]
            if test_value.dimensionality.get('[time]') != 1:
                listed_lines = consolidate_lines(line_nums)
                errors.append(
                    f'  No time dimension in numerator of capacity entry at rows {listed_lines}:  {expr}'
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
                logger.error('Unknown units format: %s', format_type)
    return res, errors


def check_database(db_path: Path) -> list[str]:
    """Check all tables in database for units compliance"""
    errors = []
    conn = sqlite3.connect(db_path)

    for table in tables_with_units:
        table_errors = check_table(conn, table)
        errors.extend(table_errors)

    conn.close()
    return errors


if __name__ == '__main__':
    from definitions import PROJECT_ROOT

    test_db = Path(PROJECT_ROOT) / 'data_files/mike_US/US_9R_8D_v3_stability_v3_1.sqlite'
    results = check_database(test_db)

    if results:
        print('\nErrors found:')
        for error in results:
            print(error)
    else:
        print('\nNo errors found')
