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
Created on:  3/21/24

Utility to transition a Version 3.0 Database to 3.1

Dev Note:  By copying data into the new schema (instead of adding columns) we can (a) control the sequence of the
columns (a nice touch, but the program should not be relying on this) and (b) capture any upgrades to FK's or
such in the new schema.

Dev Note:  This will also work if the "units" column is already added to the legacy DB, perhaps in non-standard location

Version 3.1 *only* adds the "units" to various tables.  No new tables are introduced
"""

import argparse
import sqlite3
import sys
from pathlib import Path


direct_transfer_tables = [
    'MetaDataReal',
    'OutputDualVariable',
    'SectorLabel',
    'CapacityCredit',
    'CapacityFactorProcess',
    'CapacityFactorTech',
    'CommodityType',
    'CostEmission',
    'CostFixed',
    'CostInvest',
    'CostVariable',
    'Demand',
    'DemandSpecificDistribution',
    'LoanRate',
    'EmissionActivity',
    'ExistingCapacity',
    'TechGroup',
    'GrowthRateMax',
    'GrowthRateSeed',
    'LinkedTech',
    'MaxActivity',
    'MaxCapacity',
    'MaxResource',
    'MinActivity',
    'MaxCapacityGroup',
    'MinCapacity',
    'MinCapacityGroup',
    'PlanningReserveMargin',
    'RampDown',
    'RampUp',
    'Region',
    'TimeSegmentFraction',
    'StorageInit',
    'TechnologyType',
    'TechInputSplit',
    'TechInputSplitAverage',
    'TechOutputSplit',
    'TimeOfDay',
    'TimePeriod',
    'TimeSeason',
    'TimePeriodType',
    'MaxActivityShare',
    'MaxCapacityShare',
    'MaxAnnualCapacityFactor',
    'MaxNewCapacity',
    'MaxNewCapacityGroup',
    'MaxNewCapacityShare',
    'MinActivityShare',
    'MinAnnualCapacityFactor',
    'MinCapacityShare',
    'MinNewCapacity',
    'MinNewCapacityGroup',
    'MinNewCapacityShare',
    'MinActivityGroup',
    'EmissionLimit',
    'MaxActivityGroup',
    'RPSRequirement',
    'TechGroupMember',
    'Technology',
]
# transfer with omission (allow new schema values to persist) or modification (Not Implemented)
# omits are field, value tuples in the given table
transfer_with_mod = {'MetaData': {'omits': [('element', 'DB_MAJOR'), ('element', 'DB_MINOR')]}}

add_units_tables = [
    'OutputObjective',
    'CapacityToActivity',
    'Commodity',
    'Efficiency',
    'LoanLifetimeTech',
    'LifetimeProcess',
    'LifetimeTech',
    'OutputCurtailment',
    'OutputNetCapacity',
    'OutputBuiltCapacity',
    'OutputRetiredCapacity',
    'OutputFlowIn',
    'OutputFlowOut',
    'StorageDuration',
    'OutputEmission',
    'OutputCost',
]

parser = argparse.ArgumentParser()
parser.add_argument(
    '--source',
    help='Path to original database',
    required=True,
    action='store',
    dest='source_db',
)
parser.add_argument(
    '--schema',
    help='Path to schema file (default=data_files/temoa_schema_v3_1.sql)',
    required=False,
    dest='schema',
    default='data_files/temoa_schema_v3_1.sql',
)
options = parser.parse_args()
legacy_db: Path = Path(options.source_db)
schema_file = Path(options.schema)

new_db_name = legacy_db.stem + '_v3_1.sqlite'
new_db_path = Path(legacy_db.parent, new_db_name)
# check that destination doesn't exist already
if new_db_path.exists():
    print(f'ERROR: destination database already exists: {new_db_path}. Exiting.')
    sys.exit(-1)


def exit_on_failure(msg):
    print(
        'Transition failed for reason below.  This issue is fatal and must be remediated.  Exiting.'
    )
    print(msg)
    con_old.close()
    con_new.close()
    new_db_path.unlink()
    sys.exit(-1)


con_old = sqlite3.connect(legacy_db)
con_new = sqlite3.connect(new_db_path)
cur = con_new.cursor()


# bring in the new schema and execute to build new db
with open(schema_file, 'r') as src:
    sql_script = src.read()
con_new.executescript(sql_script)

# turn off FK verification while process executes
con_new.execute('PRAGMA foreign_keys = 0;')

# belt & suspenders check that we have all tables in the schema covered

table_query_result = con_new.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
).fetchall()
v31_tables = {t[0] for t in table_query_result}

covered = set(direct_transfer_tables + add_units_tables + list(transfer_with_mod.keys()))
deltas = v31_tables ^ covered
if deltas:
    missing = v31_tables - covered
    extra = covered - v31_tables
    print(f'ERROR:  missing tables (from transfer list): {missing}')
    print(f"ERROR:  extra tables (that don't exist in schema): {extra}")
    exit_on_failure('Missing transfer tables list does not match schema.')


# execute the direct transfers
print('\n --- Executing direct transfers ---')
for table_name in direct_transfer_tables:
    try:
        # Get column names from both databases
        old_cols = [
            row[1] for row in con_old.execute(f'PRAGMA table_info({table_name})').fetchall()
        ]
        new_cols = [
            row[1] for row in con_new.execute(f'PRAGMA table_info({table_name})').fetchall()
        ]

        if set(old_cols) != set(new_cols):
            print(f'WARNING: Column mismatch in {table_name}')
            print(f'Old columns: {old_cols}')
            print(f'New columns: {new_cols}')
            exit_on_failure(f'Column mismatch in {table_name}')

        # Get data from old database with explicit column order
        cols_str = ', '.join(new_cols)
        data = con_old.execute(f'SELECT {cols_str} FROM {table_name}').fetchall()
    except sqlite3.OperationalError:
        print(f'TABLE NOT FOUND: {table_name} (creating blank table)')
        data = []
        continue

    if not data:
        print(f'No data for {table_name} (transferring blank table)')
        continue

    # Construct insert query with explicit columns
    placeholders = ','.join(['?' for _ in range(len(new_cols))])
    cols_str = ', '.join(new_cols)
    query = f'INSERT OR REPLACE INTO {table_name} ({cols_str}) VALUES ({placeholders})'
    con_new.executemany(query, data)
    con_new.commit()
    print(f'inserted {len(data)} rows into {table_name}')

# execute transfer with modifications
print('\n --- Executing transfers with modifications ---')
for table_name, mod_dict in transfer_with_mod.items():
    try:
        # Get column names from both databases
        old_cols = [
            row[1] for row in con_old.execute(f'PRAGMA table_info({table_name})').fetchall()
        ]
        new_cols = [
            row[1] for row in con_new.execute(f'PRAGMA table_info({table_name})').fetchall()
        ]
        if set(old_cols) != set(new_cols):
            print(f'ERROR: Column mismatch in {table_name}')
            print(f'Old columns: {old_cols}')
            print(f'New columns: {new_cols}')
            exit_on_failure(f'Column mismatch in {table_name}')
        # Get data from old database with explicit column order
        cols_str = ', '.join(new_cols)

        # make exclusion statement
        where = ' AND '.join(f'{field} != ?' for field, _ in mod_dict['omits'])
        params = tuple(v for _, v in mod_dict['omits'])
        data = con_old.execute(
            f'SELECT {cols_str} FROM {table_name} WHERE {where}',
            params,
        ).fetchall()

    except sqlite3.OperationalError:
        print(f'TABLE NOT FOUND: {table_name} (using default from schema)')
        continue

    # Construct insert query with explicit columns
    placeholders = ','.join(['?' for _ in range(len(new_cols))])
    query = f'INSERT OR REPLACE INTO {table_name} ({cols_str}) VALUES ({placeholders})'
    con_new.executemany(query, data)
    print(f'inserted {len(data)} rows into {table_name}')


# do the tables with units added
print('\n --- Adding "units" to tables with units added ---')
for table_name in add_units_tables:
    try:
        # Get column names from both databases
        old_cols = [
            row[1] for row in con_old.execute(f'PRAGMA table_info({table_name})').fetchall()
        ]
        new_cols = [
            row[1] for row in con_new.execute(f'PRAGMA table_info({table_name})').fetchall()
        ]

        if set(old_cols + ['units']) != set(new_cols):
            print(
                f'WARNING: Column mismatch in {table_name}.  NO DATA TRANSFERRED FOR THIS TABLE.  '
                'MUST DO MANUALLY or ALIGN AND RE-RUN AGENT.'
            )
            print(f'Old columns: {old_cols}')
            print(f'New columns: {new_cols}')
            continue

        # Get data from old database with explicit column order
        cols_str = ', '.join(old_cols)
        data = con_old.execute(f'SELECT {cols_str} FROM {table_name}').fetchall()
    except sqlite3.OperationalError:
        print(f'TABLE NOT FOUND: {table_name} (creating blank table)')
        data = []
        continue

    if not data:
        print(f'No data for {table_name} (transferring blank table)')
        continue

    # Construct insert query with explicit columns
    placeholders = ','.join(['?' for _ in range(len(old_cols))])
    query = f'INSERT OR REPLACE INTO {table_name} ({cols_str}) VALUES ({placeholders})'
    con_new.executemany(query, data)
    print(f'inserted {len(data)} rows into {table_name}')


con_new.commit()
con_new.execute('VACUUM;')
con_new.execute('PRAGMA FOREIGN_KEYS=1;')
try:
    data = con_new.execute('PRAGMA FOREIGN_KEY_CHECK;').fetchall()
    print('FK check fails (MUST BE FIXED):')
    if not data:
        print('\tNo Foreign Key Failures.  (Good news!)')
    else:
        print('\t(Table, Row ID, Reference Table, (fkid) )')
        for row in data:
            print(f'\t{row}')
except sqlite3.OperationalError as e:
    print('Foreign Key Check FAILED on new DB.  Something may be wrong with schema.')
    print(e)

# move the GlobalDiscountRate
# move the myopic base year
# sanity check...

qry = 'SELECT * FROM TimePeriod'
res = con_new.execute(qry).fetchall()
if res:
    print(f'TimePeriod table has {len(res)} rows')
    for t in res[:5]:
        print(t)
else:
    print('TimePeriod table is empty')
con_new.close()
con_old.close()
