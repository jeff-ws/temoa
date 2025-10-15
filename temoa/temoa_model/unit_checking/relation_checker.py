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
from collections.abc import Iterable
from pathlib import Path

from mypy.checkexpr import defaultdict
from mypy.message_registry import NamedTuple
from pint.registry import Unit

from definitions import PROJECT_ROOT
from temoa.temoa_model.unit_checking import ureg
from temoa.temoa_model.unit_checking.common import (
    RATIO_ELEMENT,
    SINGLE_ELEMENT,
    consolidate_lines,
    CostTableData,
)
from temoa.temoa_model.unit_checking.entry_checker import (
    validate_units_format,
    validate_units_expression,
)

logger = logging.getLogger(__name__)


def make_commodity_lut(conn: sqlite3.Connection) -> dict[str, Unit]:
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
            res[comm] = units
    return res


def make_c2a_lut(conn: sqlite3.Connection) -> dict[str, Unit]:
    """Get a dictionary of the units for each capacity to activity entry"""
    res = {}
    cursor = conn.cursor()
    query = 'SELECT tech, units FROM CapacityToActivity'
    cursor.execute(query)
    rows = cursor.fetchall()
    for comm, units in rows:
        valid, group = validate_units_format(units, SINGLE_ELEMENT)
        if valid:
            valid, units = validate_units_expression(group[0])
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
        invalid_input_flag = input_units != comm_units[ic]
        invalid_output_flag = output_units != comm_units[oc]
        if invalid_input_flag or invalid_output_flag:
            logger.warning(
                'Efficiency units conflict with associated commodity for Technology %s near row %d',
                tech,
                idx,
            )
            msg = f"\n  Expected:  {f'{ic} [{input_units}]' :^25} ----> {tech :^20} ----> {f'{oc} [{output_units}]': ^25}"
            if invalid_input_flag:
                msg += f'\n    Invalid input units: {comm_units[ic]}'
            if invalid_output_flag:
                msg += f'\n    Invalid output units: {comm_units[oc]}'
            error_msgs.append(msg)

        # check that the output of this technology is consistent in units with other instances of same tech
        if tech in res:
            if res[tech].output_units != output_units:
                logger.warning(
                    'Efficiency units conflict with same-name tech for Technology %s near row %d',
                    tech,
                    idx,
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
    conn: sqlite3.Connection,
    table_name,
    tech_lut: dict[str, IOUnits],
    c2a_lut: dict[str, Unit],
    capacity_based: bool,
) -> list[str]:
    """check the tech and units in the given table vs. baseline values for the tech"""
    error_msgs = []
    if capacity_based:
        query = (
            f'SELECT {table_name}.tech, {table_name}.units, ca.units '
            f'FROM {table_name} JOIN CapacityToActivity ca '
            f'ON {table_name}.tech = ca.tech AND {table_name}.region = ca.region'
        )
    else:
        query = f'SELECT tech, units, NULL FROM {table_name}'

    try:
        rows = conn.execute(query).fetchall()
    except sqlite3.OperationalError:
        logger.error('failed to process query: %s when processing table %s', query, table_name)
        msg = f'Failed to process table {table_name}.  See log for failed query.'
        error_msgs.append(msg)
        return error_msgs
    for idx, (tech, table_units, c2a_units) in enumerate(rows, start=1):
        if tech not in tech_lut:
            error_msgs.append(
                f'Unprocessed row (missing reference for tech "{tech}" --see earlier tests): {idx}'
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
            error_msgs.append(f'Unprocessed row (invalid units--see earlier tests): {idx}')
        if not c2a_valid:
            error_msgs.append(f'Unprocessed row (invalid c2a units--see earlier tests): {idx}')
        if not valid_table_units or not c2a_valid:
            continue

        # if we have valid c2a units, combine them to get the units of activity
        if valid_c2a_units:
            res_units = valid_table_units * (valid_c2a_units * ureg.year)

        else:
            res_units = valid_table_units

        # check that the res_units match the expectation from the tech
        if tech_lut[tech].output_units != res_units:
            error_msgs.append(
                f'Units mismatch at row {idx}. Table Entry: {valid_table_units}, '
                f'{f" C2A Entry: {valid_c2a_units}, " if valid_c2a_units else ""}'
                f'expected: {tech_lut[tech].output_units / (valid_c2a_units * ureg.year) if valid_c2a_units else tech_lut[tech].output_units}'
                f' for output of tech {tech}.'
            )

    return error_msgs


def check_cost_tables(
    conn: sqlite3.Connection,
    cost_tables: Iterable[CostTableData],
    tech_lut: dict[str, IOUnits],
    c2a_lut: dict[str, Unit],
    commodity_lut: dict[str, Unit],
) -> list[str]:
    """
    Check all cost tables for (a) alignment of units to tech output (the denominator) and (b) 100% commonality
    in the cost units (numerator)
    Note:  we'll *assume* the first passing entry in the first table establishes the common cost units and
           check for consistency
    """
    common_cost_unit = None  # Expectation:  MUSD.  Something with a prefix and currency dimension
    error_msgs = []
    for ct in cost_tables:
        table_grouped_errors = defaultdict(list)
        if ct.commodity_reference and ct.capacity_based:
            raise ValueError(
                f'Table that is "capacity based" {ct.table_name} flagged as having commodity field.  Check input for cost tables'
            )
        query = f'SELECT {ct.commodity_reference if ct.commodity_reference else 'tech'}, units FROM {ct.table_name}'
        try:
            rows = conn.execute(query).fetchall()
        except sqlite3.OperationalError:
            logger.error(
                'failed to process query: %s when processing table %s', query, ct.table_name
            )
            msg = f'Failed to process table {ct.table_name}.  See log for failed query.'
            error_msgs.append(msg)
            continue
        for idx, (tech, raw_units_expression) in enumerate(rows, start=1):
            # convert to pint expression
            valid, table_units = validate_units_expression(raw_units_expression)
            if not valid:
                label = f'  {ct.table_name}:  Unprocessed row (invalid units--see earlier tests): {raw_units_expression}'
                table_grouped_errors[label].append(idx)
                continue

            # for those costs that are capacity-based, we will adjust the commodity's units (which are activity-based)
            # by dividing them by the C2A factor, which should make them comparable.
            #
            # Example:
            #    $/MW  (Capacity based cost from a table)
            #    MWh   (The commodity's base units as an Activity-based (energy))
            #
            #    h     (the C2A factor to get from MW to MWh
            #
            #    so we take MWh / h =>  MW is the expected comparison point after removing the $ reference

            # find the referenced commodity units from the tech or commodity depending on table structure...
            if ct.commodity_reference:
                commodity_units = commodity_lut.get(ct.commodity_reference)
                if not commodity_units:
                    label = f'{ct.table_name}:  Unprocessed row (unknown commodity: {ct.commodity_reference}) '
                    table_grouped_errors[label].append(idx)
                    continue
            else:
                tech_io = tech_lut.get(tech)
                if tech_io:
                    commodity_units = tech_io.output_units
                else:
                    label = f'{ct.table_name}:  Unprocessed row (unknown tech: {tech}) '
                    table_grouped_errors[label].append(idx)
                    continue

            # pull the C2A factor if this table is capacity-based and determine the "match units" which should
            # match the commodity units in the table, after removing the "per period" time factor, if it exists
            c2a_units = None
            if ct.capacity_based:
                c2a_units = c2a_lut.get(tech, ureg.dimensionless)  # default is dimensionless
                # we need to transform the activity-based commodity units to capacity units to match the cost table
                match_units = commodity_units / (c2a_units * ureg.year)
            else:
                match_units = commodity_units

            # now we "sit on this" so we can remove the common cost below for checking, after it is established

            if common_cost_unit is None:
                # establish it

                #
                # Typical "cost math" is like:
                #
                #      MUSD
                #      ----     *    kWh  =  MUSD
                #      kWh

                # determine if the units are a "clean cost" as shown above

                cost_unit = (
                    table_units * match_units
                )  # should simplify to pure currency as shown above
                if ct.period_based:
                    # multiply by the standard period to remove it from the denominator
                    cost_unit *= ureg.year
                # check that what we have captured is in the currency dimension == "clean"
                # dev note:  multiplying by 1 allows us to use the check_units_expression() function
                if (1 * cost_unit).check('[currency]'):
                    common_cost_unit = cost_unit
                else:
                    # something is wrong, hopefully it was just this entry?
                    # mark it, dump it, and try again...
                    error_msgs.append(
                        f'{ct.table_name}:  Unprocessed row (unreducible cost units or mismatched tech output units): {idx}'
                    )
                    continue
            else:
                # use the match_units from the associated tech/commodity to remove the non-cost units
                cost_unit = table_units * match_units
                if ct.period_based:
                    cost_unit *= ureg.year

                # check 1:  ensure the cost units are equal to the common cost units
                if cost_unit != common_cost_unit:
                    label = (
                        f'{ct.table_name}:  Non-standard cost found (does not simplify to expected common cost unit): {raw_units_expression}'
                        f'\n    Commodity units: {commodity_units}, Residual (expecting {common_cost_unit}): {cost_unit}, c2a units: {c2a_units if c2a_units else "N/A"}.'
                    )
                    table_grouped_errors[label].append(idx)
                else:
                    # proceed to the follow-on check
                    # check 2: ensure that the commodity units match the commodity,
                    # now that we can remove the common cost and check that the plain units matches the denominator
                    plain_units = common_cost_unit / table_units
                    if match_units != plain_units:
                        label = f'{ct.table_name}:  Commodity units of cost element incorrect after applying C2A factor: {raw_units_expression}.'
                        table_grouped_errors[label].append(idx)
        for label, listed_lines in table_grouped_errors.items():
            error_msgs.append(f'{label} at rows: {consolidate_lines(listed_lines)}')
    return error_msgs


def main(db_path: Path):
    """Run unit relationship checks on database"""
    logging.basicConfig(level=logging.INFO)

    try:
        conn = sqlite3.connect(db_path)
        comm_units = make_commodity_lut(conn)
        check_efficiency_table(conn, comm_units)
        conn.close()
    except sqlite3.Error as e:
        logger.error(f'Database error: {e}')
    except Exception as e:
        logger.error(f'Error during check: {repr(e)}')
        raise


if __name__ == '__main__':
    main(Path(PROJECT_ROOT) / 'data_files/mike_US/US_9R_8D_v3_stability_v3_1.sqlite')
