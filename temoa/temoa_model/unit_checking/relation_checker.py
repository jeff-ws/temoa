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

A systematic check of expected relationships between tables to ensure units are consistent

"""
import logging
import sqlite3
from pathlib import Path

from mypy.message_registry import NamedTuple
from pint.registry import Unit

from definitions import PROJECT_ROOT
from temoa.temoa_model.unit_checking.common import (
    RATIO_ELEMENT,
    SINGLE_ELEMENT,
    MIXED_UNITS,
    consolidate_lines,
)
from temoa.temoa_model.unit_checking.entry_checker import validate_units_format

logger = logging.getLogger(__name__)


def commodity_units(conn: sqlite3.Connection) -> dict[str, str]:
    """Get a dictionary of the units for each commodity entry"""
    res = {}
    cursor = conn.cursor()
    query = 'SELECT name, units FROM commodity'
    cursor.execute(query)
    rows = cursor.fetchall()
    for comm, units in rows:
        valid, group = validate_units_format(units, SINGLE_ELEMENT)
        if not valid:
            continue
            # raise RuntimeError(f"Invalid units for commodity: {comm} {units}")
        res[comm] = group[0]
    return res


class IOUnits(NamedTuple):
    input_units: str
    output_units: str


def check_efficiency_table(
    conn: sqlite3.Connection, comm_units: dict[str, str]
) -> tuple[dict[str, IOUnits], list[str]]:
    """
    Check the technology units for Efficiency table entries

    Returns a dictionary of technology to IOUnits and a list of error messages

    """

    query = 'SELECT tech, input_comm, output_comm, units FROM efficiency'
    rows = conn.execute(query).fetchall()
    res = {}
    error_msgs = []
    invalid_rows = []
    for idx, (tech, ic, oc, units) in enumerate(rows, start=1):
        valid, located_units = validate_units_format(units, RATIO_ELEMENT)
        if not valid:
            invalid_rows.append(idx)
            continue
        output_units, input_units = located_units
        invalid_input = input_units != comm_units[ic] and input_units != MIXED_UNITS
        invalid_output = output_units != comm_units[oc]
        if invalid_input or invalid_output:
            logger.warning('Units conflict for Technology %s near row %d', tech, idx)
            msg = f"\n  Expected:  {f'{ic} [{input_units}]' :^25} ----> {tech :^20} ----> {f'{oc} [{output_units}]': ^25}"
            if invalid_input:
                msg += f'\n    Invalid input units: {comm_units[ic]}'
            if invalid_output:
                msg += f'\n    Invalid output units: {comm_units[oc]}'
            error_msgs.append(msg)
        else:
            res[tech] = IOUnits(input_units, output_units)
    if invalid_rows:
        listed_lines = consolidate_lines(invalid_rows)
        line_error_msg = f'Non-processed rows (see earlier tests): {listed_lines}'
        error_msgs.append(line_error_msg)

    return res, error_msgs


def check_inter_table_relations(
    source_relations: dict[str, Unit], table_relations: dict[str, IOUnits]
) -> tuple[dict[str, str], list[str]]:
    pass


def main(db_path: Path):
    """Run unit relationship checks on database"""
    logging.basicConfig(level=logging.INFO)

    try:
        conn = sqlite3.connect(db_path)
        comm_units = commodity_units(conn)
        check_efficiency_table(conn, comm_units)
        conn.close()
    except sqlite3.Error as e:
        logger.error(f'Database error: {e}')
    except Exception as e:
        logger.error(f'Error during check: {repr(e)}')
        raise


if __name__ == '__main__':
    main(Path(PROJECT_ROOT) / 'data_files/mike_US/US_9R_8D_v3_stability_v3_1.sqlite')
