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
from temoa.temoa_model.unit_checking.common import tables_with_units
from temoa.temoa_model.unit_checking.table_checker import check_table

logger = logging.getLogger(__name__)
verbose = True  # for dev/test work


def screen(dp_path: Path, report_path: Path | None = None):
    """The sequencer to run a series of checks on units in the database"""
    report_entries = []
    with sqlite3.connect(dp_path) as conn:
        # test 1:  DB version
        data = conn.execute('SELECT element, value FROM MetaData').fetchall()
        meta_data = dict(data)
        major = meta_data.get('DB_MAJOR', 0)
        minor = meta_data.get('DB_MINOR', 0)
        if major == 3 and minor >= 1:
            msg = 'Units Check 1 (DB Version):  Passed'
            report_entries.extend((msg, '\n'))
            logger.info(msg)
            if verbose:
                print(f'Units Check 1 (DB Version):  Passed')
        else:
            msg = 'Units Check 1 (DB Version):  Failed.  DB must be v3.1 or greater for units checking'
            report_entries.extend((msg, '\n'))
            logger.warning(msg)
            return
        report_entries.append('\n')

        # test 2:  Units in tables
        msg = 'Units Check 2 (Units Entries in Tables):  Started'
        logger.info(msg)
        report_entries.extend((msg, '\n'))
        errors = False
        for table in tables_with_units:
            table_errors = check_table(conn, table)
            if table_errors:
                errors = True
                for error in table_errors:
                    logger.warning('%s: %s', table, error)
                    report_entries.extend((f'{table}: {error}', '\n'))
                    if verbose:
                        print(f'{table}: {error}')
        if not errors:
            msg = 'Units Check 2 (Units Entries in Tables):  Passed'
            logger.info(msg)
            report_entries.extend((msg, '\n'))
        report_entries.append('\n')

    if report_path:
        with open(report_path, 'w') as report_file:
            report_file.writelines(report_entries)


if __name__ == '__main__':
    db_path = Path(PROJECT_ROOT) / 'data_files/mike_US/US_9R_8D_v3_stability_v3_1.sqlite'
    screen(db_path, report_path=Path(PROJECT_ROOT) / 'output_files/units.txt')
