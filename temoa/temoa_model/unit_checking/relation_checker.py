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
import dataclasses
import logging
import sqlite3
from collections import defaultdict
from collections.abc import Iterable

from pint.registry import Unit

from temoa.temoa_model.unit_checking import ureg
from temoa.temoa_model.unit_checking.common import (
    RATIO_ELEMENT,
    SINGLE_ELEMENT,
    consolidate_lines,
    CostTableData,
    RelationType,
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


@dataclasses.dataclass(frozen=True)
class IOUnits:
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
            # we give up early.  The specifics of why this failed should be evident in earlier tests
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
    comm_lut: dict[str, Unit],
    relation_type: RelationType,
) -> list[str]:
    """check the tech and units in the given table vs. baseline (expected) values for the tech"""
    grouped_errors = defaultdict(list)
    match relation_type:
        case RelationType.CAPACITY:
            # we make a query to join on the C2A units to pick those up
            query = (
                f'SELECT {table_name}.tech, {table_name}.units, ca.units '
                f'FROM {table_name} JOIN CapacityToActivity ca '
                f'ON {table_name}.tech = ca.tech AND {table_name}.region = ca.region'
            )
        # otherwise, fill the C2A with NULL
        case RelationType.ACTIVITY:
            query = f'SELECT tech, units, NULL FROM {table_name}'
        case RelationType.COMMODITY:
            query = f'SELECT commodity, units, NULL FROM {table_name}'
        case _:
            raise ValueError(f'Unexpected relation type: {relation_type}')
    try:
        rows = conn.execute(query).fetchall()
    except sqlite3.OperationalError:
        logger.error('failed to process query: %s when processing table %s', query, table_name)
        msg = f'Failed to process table {table_name}.  See log for failed query.'
        return [msg]

    # process the rows
    for idx, (tech_or_comm, table_units, c2a_units) in enumerate(rows, start=1):
        expected_units = None
        match relation_type:
            case RelationType.CAPACITY:
                io_units = tech_lut.get(tech_or_comm)
                if not io_units:
                    grouped_errors[
                        f'Unprocessed row (missing reference for tech "{tech_or_comm}" --see earlier tests)'
                    ].append(idx)
                    continue
                expected_units = io_units.output_units
            case RelationType.ACTIVITY:
                io_units = tech_lut[tech_or_comm]
                if not io_units:
                    grouped_errors[
                        f'Unprocessed row (missing reference for tech "{tech_or_comm}" --see earlier tests)'
                    ].append(idx)
                    continue
                expected_units = io_units.output_units
            case RelationType.COMMODITY:
                expected_units = comm_lut.get(tech_or_comm)
            case _:
                raise ValueError(f'Unexpected relation type: {relation_type}')
        if not expected_units:
            grouped_errors[
                f'Unprocessed row (missing reference for tech "{tech_or_comm}" --see earlier tests)'
            ].append(idx)
            continue

        # validate the units in the table...
        entry_format_valid, units_data = validate_units_format(table_units, SINGLE_ELEMENT)
        if entry_format_valid:
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
        else:  # we are in a valid state: no C2A units provided/needed
            c2a_valid = True
            valid_c2a_units = None

        if not valid_table_units:
            grouped_errors['Unprocessed row (invalid units--see earlier tests)'].append(idx)
        if not c2a_valid:
            grouped_errors['Unprocessed row (invalid c2a units--see earlier tests)'].append(idx)
        if not valid_table_units or not c2a_valid:
            continue

        # if we have valid c2a units, combine them to get the units of activity
        if valid_c2a_units:
            res_units = valid_table_units * (valid_c2a_units * ureg.year)

        else:
            res_units = valid_table_units

        # check that the res_units match the expectation from the tech
        if expected_units != res_units:
            label = f'Units do not match expectation for tech/comm: {tech_or_comm}'
            conversions = []
            if valid_c2a_units:
                conversions.append(f'C2A Factor: {valid_c2a_units}')
                conversions.append(f'Nominal Period: {ureg.year}')
            detail = _ding_label(
                table_entry=table_units,
                focus=f'Converted Measure: {valid_table_units}',
                conversions=conversions,
                result=res_units,
                expectation=expected_units,
            )
            msg = label + detail + '\n'
            grouped_errors[msg].append(idx)

    # gather into list format
    res = []
    for msg, line_nums in grouped_errors.items():
        res.append(f'{msg}  at rows: {consolidate_lines(line_nums)}')

    return res


def _ding_label(table_entry, focus, conversions: Iterable[str], result, expectation) -> str:
    """Make a standardized 'ding' label to use in error reporting"""
    res = ['']
    res.append(f'|        Table Entry: {table_entry}')
    res.append(f'|    Focused Portion: {focus}')
    for conversion in conversions:
        res.append(f'|         Conversion: {conversion}')
    res.append(f'|             Result: {result}')
    res.append(f'|        Expectation: {expectation}')
    return '\n  '.join(res)


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
                f'Table that is "capacity based" {ct.table_name} flagged as '
                'having commodity field--expecting tech field.  Check data.'
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
            cost_units, measure_units = None, None
            # screen for empty/missing raw inputs
            if not raw_units_expression:
                label = f'{ct.table_name}:  Unprocessed row (missing units): {raw_units_expression}'
                table_grouped_errors[label].append(idx)
                continue
            valid, (elements) = validate_units_format(raw_units_expression, RATIO_ELEMENT)
            if valid:
                cost_valid, cost_units = validate_units_expression(elements[0])
                units_valid, measure_units = validate_units_expression(elements[1])
            else:
                cost_valid, units_valid = False, False
            if not (cost_valid and units_valid):
                label = f'{ct.table_name}:  Unprocessed row (invalid units--see earlier tests): {raw_units_expression}'
                table_grouped_errors[label].append(idx)
                continue

            # Test 1: Look for cost commonality
            if common_cost_unit is None:
                # try to establish it
                # check that what we have captured is in the currency dimension == "clean"
                # dev note:  multiplying by 1 allows us to use the check_units_expression() function
                if (1 * cost_units).check('[currency]'):
                    common_cost_unit = cost_units
                else:
                    # something is wrong, hopefully it was just this entry?
                    # mark it, dump it, and try again...
                    error_msgs.append(
                        f'{ct.table_name}:  Unprocessed row (unreducible cost units): {cost_units} at row: {idx}'
                    )
                    continue
            else:  # use the common units to test
                if cost_units != common_cost_unit:
                    label = f'{ct.table_name}:  Non-standard cost found (expected common cost units of {common_cost_unit}) got: {cost_units}'
                    table_grouped_errors[label].append(idx)

            # Test 2:  Check the units of measure to ensure alignment with the tech's output units
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
            oring_measure_units = measure_units
            if ct.capacity_based:
                c2a_units = c2a_lut.get(tech, '<none>')  # default is dimensionless
                # apply to convert
                if c2a_units != '<none>':
                    measure_units *= c2a_units
                # apply the nominal period
                measure_units *= ureg.year

            if ct.period_based:
                measure_units /= ureg.year  # remove the "per year" from this element

            matched = measure_units == commodity_units

            if not matched:
                tech_reference = ct.commodity_reference if ct.commodity_reference else tech
                label = f'{ct.table_name}:  Non-matching measure unit found in cost denominator for tech/comm: {tech_reference}:'
                conversions = []
                if ct.capacity_based:
                    conversions.append(f'C2A Factor: {c2a_units}')
                    conversions.append(f'Nominal Period: {ureg.year}')
                if ct.period_based:
                    conversions.append(f'Per-period Factor: {ureg.year}')
                detail = _ding_label(
                    table_entry=raw_units_expression,
                    focus=f'Converted Measure in Denominator: {oring_measure_units}',
                    conversions=conversions,
                    result=measure_units,
                    expectation=commodity_units,
                )
                label += f'{detail}\n'

                table_grouped_errors[label].append(idx)

        for label, listed_lines in table_grouped_errors.items():
            error_msgs.append(f'{label}  at rows: {consolidate_lines(listed_lines)}\n')
    return error_msgs
