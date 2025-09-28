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
from temoa.temoa_model.unit_checking import ureg
from temoa.temoa_model.unit_checking.common import (
    RATIO_ELEMENT,
    SINGLE_ELEMENT,
    consolidate_lines,
)
from temoa.temoa_model.unit_checking.entry_checker import (
    validate_units_format,
    validate_units_expression,
)

logger = logging.getLogger(__name__)


def commodity_units(conn: sqlite3.Connection) -> dict[str, Unit]:
    """Get a dictionary of the units for each commodity entry"""
    res = {}
    cursor = conn.cursor()
    query = 'SELECT name, units FROM commodity'
    cursor.execute(query)
    rows = cursor.fetchall()
    for comm, units in rows:
        valid, group = validate_units_format(units, SINGLE_ELEMENT)
        if valid:
            valid, units = validate_units_expression(group[0])
        if not valid:
            continue
        res[comm] = units
    return res


class IOUnits(NamedTuple):
    input_units: Unit
    output_units: Unit


def check_efficiency_table(
    conn: sqlite3.Connection, comm_units: dict[str, str]
) -> tuple[dict[str, IOUnits], list[str]]:
    """
    Check the technology units for Efficiency table entries

    Returns a dictionary of technology : IOUnits and a list of error messages

    """

    query = 'SELECT tech, input_comm, output_comm, units FROM efficiency'
    rows = conn.execute(query).fetchall()
    res = {}
    error_msgs = []
    invalid_rows = []
    for idx, (tech, ic, oc, units) in enumerate(rows, start=1):
        input_units, output_units = None, None
        valid, located_units = validate_units_format(units, RATIO_ELEMENT)
        if valid:
            valid, output_units = validate_units_expression(located_units[0])
        if valid:
            valid, input_units = validate_units_expression(located_units[1])
        if not valid:
            invalid_rows.append(idx)
            continue

        # check that our tech matches the units of the connected commodities
        invalid_input = input_units != comm_units[ic]
        invalid_output = output_units != comm_units[oc]
        if invalid_input or invalid_output:
            logger.warning(
                'Units conflict with linked commodity for Technology %s near row %d', tech, idx
            )
            msg = f"\n  Expected:  {f'{ic} [{input_units}]' :^25} ----> {tech :^20} ----> {f'{oc} [{output_units}]': ^25}"
            if invalid_input:
                msg += f'\n    Invalid input units: {comm_units[ic]}'
            if invalid_output:
                msg += f'\n    Invalid output units: {comm_units[oc]}'
            error_msgs.append(msg)

        # check that the output of this technology is consistent in units with other instances of same tech
        if tech in res:
            if res[tech].output_units != output_units:
                logger.warning(
                    'Units conflict with same-name tech for Technology %s near row %d', tech, idx
                )
                msg = f"\n  Found:  {f'{ic} [{input_units}]' :^25} ----> {tech :^20} ----> {f'{oc} [{output_units}]': ^25}"
                msg += f'\n    Conflicting output units: {res[tech].output_units} vs {output_units}'
                error_msgs.append(msg)

        else:
            res[tech] = IOUnits(input_units, output_units)

    # we gather all non-processed rows in one statement here due to size of table vs. individual reporting
    if invalid_rows:
        listed_lines = consolidate_lines(invalid_rows)
        line_error_msg = f'Non-processed rows (see earlier tests): {listed_lines}'
        error_msgs.append(line_error_msg)

    return res, error_msgs


def check_inter_table_relations(
    conn: sqlite3.Connection, table_name, tech_units: dict[str, IOUnits], capacity_based: bool
) -> list[str]:
    """check the tech and units in the given table vs. baseline values for the tech"""
    error_msgs = []
    if capacity_based:
        query = f'SELECT {table_name}.tech, {table_name}.units, ca.units FROM {table_name} JOIN CapacityToActivity ca ON {table_name}.tech = ca.tech'
    else:
        query = f'SELECT tech, units, NULL FROM {table_name}'

    try:
        rows = conn.execute(query).fetchall()
    except sqlite3.OperationalError as e:
        logger.error('failed to process query: %s when processing table %s', query, table_name)
        return error_msgs
    for idx, (tech, table_units, c2a_units) in enumerate(rows, start=1):
        if tech not in tech_units:
            error_msgs.append(
                f'  Unprocessed row (missing reference for tech "{tech}" --see earlier tests): {idx}'
            )
            continue
        # validate the units in the table...
        table_valid, units_data = validate_units_format(table_units, SINGLE_ELEMENT)
        if table_valid:
            _, valid_table_units = validate_units_expression(units_data[0])
        else:
            valid_table_units = None

        # validate the c2a units, if needed
        if c2a_units:
            c2a_valid, units_data = validate_units_format(c2a_units, SINGLE_ELEMENT)
            if c2a_valid:
                # further ensure the conversion is valid and retain the validity
                c2a_valid, valid_c2a_units = validate_units_expression(units_data[0])
            else:
                valid_c2a_units = None
        else:  # we are in a valid state, but no units to use for c2a
            c2a_valid = True
            valid_c2a_units = None

        if not valid_table_units:
            error_msgs.append(f'  Unprocessed row (invalid units--see earlier tests): {idx}')
        if not c2a_valid:
            error_msgs.append(f'  Unprocessed row (invalid c2a units--see earlier tests): {idx}')
        if not valid_table_units or not c2a_valid:
            continue

        # if we have valid c2a units, combine them to get the units of activity
        if valid_c2a_units:
            res_units = valid_table_units * (valid_c2a_units * ureg.year)

        else:
            res_units = valid_table_units

        # check that the res_units match the expectation from the tech
        if tech_units[tech].output_units != res_units:
            error_msgs.append(
                f'  Units mismatch near row {idx}:  Table Entry: {valid_table_units}, '
                f'C2A Entry: {valid_c2a_units if valid_c2a_units else 'N/A'}, '
                f'expected: {  tech_units[tech].output_units / (valid_c2a_units * ureg.year) if valid_c2a_units else {tech_units[tech].output_units}}'
            )

    return error_msgs


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
