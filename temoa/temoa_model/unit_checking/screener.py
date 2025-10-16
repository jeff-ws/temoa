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
Created on:  9/25/25

The main executable to screen for units in a v3.1 database

"""
import logging
import sqlite3
from pathlib import Path

from definitions import PROJECT_ROOT
from temoa.temoa_model.unit_checking.common import (
    tables_with_units,
    capacity_based_tables,
    activity_based_tables,
    cost_based_tables,
)
from temoa.temoa_model.unit_checking.relation_checker import (
    check_efficiency_table,
    make_commodity_lut,
    check_inter_table_relations,
    check_cost_tables,
    make_c2a_lut,
)
from temoa.temoa_model.unit_checking.table_checker import check_table

logger = logging.getLogger(__name__)
verbose = True  # for dev/test work


def screen(dp_path: Path, report_path: Path | None = None):
    """The sequencer to run a series of checks on units in the database"""
    report_entries = []
    table_units = {}
    """Table name : {tech | commodity: units}"""
    with sqlite3.connect(dp_path) as conn:
        # test 1: DB version
        msg = '========  Units Check 1 (DB Version):  Started ========'
        report_entries.extend((msg, '\n'))
        logger.info(msg)
        if verbose:
            print()
            print(msg)
        data = conn.execute('SELECT element, value FROM MetaData').fetchall()
        meta_data = dict(data)
        major = meta_data.get('DB_MAJOR', 0)
        minor = meta_data.get('DB_MINOR', 0)
        if major == 3 and minor >= 1:
            msg = 'Units Check 1 (DB Version):  Passed'
            report_entries.extend((msg, '\n'))
            logger.info(msg)
            if verbose:
                print(msg)
        else:
            msg = 'Units Check 1 (DB Version):  Failed.  DB must be v3.1 or greater for units checking'
            report_entries.extend((msg, '\n'))
            logger.warning(msg)
            # we are non-viable, write the (very short) report and return
            _write_report(report_path, report_entries)
            if verbose:
                print(msg)
            return

        # test 2: Units in tables
        report_entries.append('\n')
        msg = '======== Units Check 2 (Units Entries in Tables):  Started ========'
        if verbose:
            print()
            print(msg)
        logger.info(msg)
        report_entries.extend((msg, '\n'))
        errors = False
        for table in tables_with_units:
            relations, table_errors = check_table(conn, table)
            table_units[table] = relations
            if table_errors:
                errors = True
                for error in table_errors:
                    logger.info('%s: %s', table, error)
                    report_entries.extend((f'  {table}: {error}', '\n'))
                    if verbose:
                        print(f'{table}:  {error}')
        if not errors:
            msg = 'Units Check 2 (Units Entries in Tables):  Passed'
            logger.info(msg)
            report_entries.extend((msg, '\n'))
            if verbose:
                print(msg)
        report_entries.append('\n')

        # test 3: Efficiency Table
        msg = '======== Units Check 3 (Tech I/O via Efficiency Table):  Started ========'
        logger.info(msg)
        report_entries.extend((msg, '\n'))
        if verbose:
            print()
            print(msg)
        # make Look Up Tables for use in follow-on checks
        commodity_lut = make_commodity_lut(conn)
        c2a_lut = make_c2a_lut(conn)
        tech_io_lut, errors = check_efficiency_table(conn, comm_units=commodity_lut)
        if errors:
            for error in errors:
                logger.info('%s: %s', 'Efficiency', error)
                report_entries.extend((f'Efficiency: {error}', '\n'))
                if verbose:
                    print(f'Efficiency: {error}')
        else:
            msg = 'Units Check 3: (Efficiency Table and Tech I/O:  Passed'
            report_entries.extend((msg, '\n'))
            logger.info(msg)
            if verbose:
                print(msg)

        report_entries.append('\n')

        # test 4: Relationships in other tables
        # this utilizes tech_io_lut gathered above to QA the units in other tables
        msg = '======== Units Check 4 (Related Tables):  Started ========'
        logger.info(msg)
        report_entries.extend((msg, '\n'))
        if verbose:
            print()
            print(msg)
        error_free = True
        for table in activity_based_tables:
            errors = check_inter_table_relations(
                conn=conn, table_name=table, tech_lut=tech_io_lut, capacity_based=False
            )
            if errors:
                error_free = False
                for error in errors:
                    logger.info('%s: %s', table, error)
                    report_entries.extend((f'{table}:  {error}', '\n'))
                    if verbose:
                        print(f'{table}:  {error}')
        for table in capacity_based_tables:
            errors = check_inter_table_relations(
                conn=conn, table_name=table, tech_lut=tech_io_lut, capacity_based=True
            )
            if errors:
                error_free = False
                for error in errors:
                    logger.info('%s: %s', table, error)
                    report_entries.extend((f'{table}:  {error}', '\n'))
                    if verbose:
                        print(f'{table}:  {error}')
        if error_free:
            msg = 'Units Check 4: (Related Tables):  Passed'
            logger.info(msg)
            report_entries.extend((msg, '\n'))
            if verbose:
                print(msg)

        report_entries.append('\n')

        # test 5: Cost-Based Tables
        # checks to assure that the output units are compatible with the related tech and that the currency is
        # standardized when the units are simplified
        # We expect units like Mdollars/PJ or such and the denominator should align with the commodity via the tech
        msg = '======== Units Check 5 (Cost Tables):  Started ========'
        logger.info(msg)
        report_entries.extend((msg, '\n'))
        if verbose:
            print()
            print(msg)
        errors = check_cost_tables(
            conn,
            cost_tables=cost_based_tables,
            tech_lut=tech_io_lut,
            c2a_lut=c2a_lut,
            commodity_lut=commodity_lut,
        )
        if errors:
            for error in errors:
                logger.info('%s', error)
                report_entries.extend((error, '\n'))
                if verbose:
                    print(error)
        else:
            msg = 'Units Check 5: (Cost Tables):  Passed'
            logger.info(msg)
            report_entries.extend((msg, '\n'))
            if verbose:
                print(msg)

        # wrap it up
        _write_report(report_path, report_entries)


def _write_report(report_path: Path, report_entries: list[str]):
    """Write the report to file"""
    if not report_path:
        return
    with open(report_path, 'w', encoding='utf-8') as report_file:
        report_file.writelines(report_entries)


if __name__ == '__main__':
    db_path = Path(PROJECT_ROOT) / 'data_files/mike_US/US_9R_8D_v3_stability_v3_1.sqlite'
    screen(db_path, report_path=Path(PROJECT_ROOT) / 'output_files/units.txt')
