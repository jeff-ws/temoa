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

from temoa.temoa_model.unit_checking.common import (
    tables_with_units,
    ratio_units_tables,
    RATIO_ELEMENT,
    SINGLE_ELEMENT,
    ACCEPTABLE_CHARACTERS,
)
from temoa.temoa_model.unit_checking.entry_checker import (
    validate_units_expression,
    validate_units_format,
    gather_from_table,
)

logger = logging.getLogger(__name__)


def check_table(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """Check all entries in a table for format and registry compliance"""
    errors = []
    format_type = RATIO_ELEMENT if table_name in ratio_units_tables else SINGLE_ELEMENT

    entries = gather_from_table(conn, table_name)
    for expr, line_nums in entries.items():
        # check characters
        valid_chars = re.search(ACCEPTABLE_CHARACTERS, expr)
        if not valid_chars:
            listed_lines = (
                line_nums
                if len(line_nums) < 5
                else f'{", ".join(str(t) for t in line_nums[:5])}", ... more"'
            )
            errors.append(
                f'Invalid character(s) in {listed_lines} [only letters, underscore and "*, /" operators allowed]: {expr}'
            )
            continue

        # Check format
        valid, elements = validate_units_format(expr, format_type)
        if not valid:
            listed_lines = (
                line_nums
                if len(line_nums) < 5
                else f'{", ".join(str(t) for t in line_nums[:5])}", ... more"'
            )
            errors.append(f'Format violation at lines {listed_lines}:  {expr}')
            continue

        # Check registry compliance
        for element in elements:
            if element:
                success, _ = validate_units_expression(element)
                if not success:
                    listed_lines = (
                        line_nums
                        if len(line_nums) < 5
                        else f'{", ".join(str(t) for t in line_nums[:5])}", ... more"'
                    )
                    errors.append(
                        f'Registry violation (UNK units) at lines {listed_lines}:  {element}'
                    )
    return errors


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
