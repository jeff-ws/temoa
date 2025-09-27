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
Created on:  9/19/25

module to check all units entries in database for...
    (1) existence :)
    (2) general format (e.g. as a singleton or a ratio expression like Lumens / (Watt))
    (3) membership in units registry

"""
import logging
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from pint import UndefinedUnitError, Unit

from definitions import PROJECT_ROOT
from temoa.temoa_model.unit_checking import ureg
from temoa.temoa_model.unit_checking.common import (
    UnitsFormat,
    RATIO_ELEMENT,
    SINGLE_ELEMENT,
)

logger = logging.getLogger(__name__)


def validate_units_expression(expr: str) -> tuple[bool, Unit]:
    """
    validate an entry against the units registry
    :param expr: the expression to validate
    :return: tuple of the validity and the converted expression
    """
    try:
        units = ureg.parse_units(expr)
        return True, units
    except UndefinedUnitError as e:
        return False, None


def validate_units_format(
    expr: str, unit_format: UnitsFormat
) -> tuple[bool, tuple[str, ...] | None]:
    """
    validate against the format
    return boolean for validity and tuple of elements if valid
    """
    if not expr:
        return False, None
    elements = re.search(unit_format.format, expr)
    if elements:
        return True, tuple(elements.groups())
    return False, None


def gather_from_table(conn: sqlite3.Connection, table: str) -> dict[str, list[int]]:
    """gather all "units" entries from a table as a list of line numbers"""

    res = defaultdict(list)
    with conn:
        cur = conn.cursor()
        cur.execute(f'SELECT units FROM {table}')
        for idx, result in enumerate(cur.fetchall(), start=1):
            res[result[0]].append(idx)

    return res


if __name__ == '__main__':
    """for development/experimentation"""
    exprs = [
        'watt',
        'meter',
        'm',
        'petajoule',
        'PJ',
        'PJ/s',
        'PeTAJouLE',
        'PetaJoule',
        'kilowatt*hour',
        'killowathour',
        'KWh',
        'KWH',
        'USD',
        'dollar',
        'passenger',
    ]
    for expr in exprs:
        success, converted = validate_units_expression(expr)
        compatible = converted.is_compatible_with(ureg('joule')) if converted else '--'
        if success:
            print(f'{expr} converts to: {converted}.  Compatible with joules: {compatible} ')
        else:
            print(f'{expr} failed to convert')

    tables = ['Efficiency', 'ExistingCapacity']
    formats = [RATIO_ELEMENT, SINGLE_ELEMENT]

    conn = sqlite3.connect(
        Path(PROJECT_ROOT) / 'data_files/mike_US/US_9R_8D_v3_stability_v3_1.sqlite'
    )

    def validate_entries(table_name, units_format: UnitsFormat):
        """validate all entries in a table"""
        conn = sqlite3.connect(
            Path(PROJECT_ROOT) / 'data_files/mike_US/US_9R_8D_v3_stability_v3_1.sqlite'
        )
        res = gather_from_table(conn, table_name)
        conn.close()
        for expr in res:
            valid, elements = validate_units_format(expr, units_format)
            if not valid:
                print(f'Format Violation: {expr} in {table_name}')
            else:
                for group in elements:
                    if group:
                        success, converted = validate_units_expression(group)
                        if not success:
                            print(f'Unit Validation Fail: {expr} in {table_name}')

    for table in tables:
        print(gather_from_table(conn, table))

    conn.close()
    print('\n\n')

    for t in zip(tables, formats):
        validate_entries(t[0], t[1])
