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
Created on:  9/9/25

This quick utility compares the schema of a built sqlite database to a reference schema in the form of a SQL file

"""
import sqlite3
import tempfile
from pathlib import Path

from definitions import PROJECT_ROOT


def table_fields(db_file: Path) -> dict[str, list[str]]:
    """
    Extract the field names from the table definitions in the sqlite database
    :param db_file: target database
    :return: dictionary of table name : list of field names
    """
    with sqlite3.connect(db_file) as con:
        cur = con.cursor()
        # Get all table definitions from sqlite_master
        tables = cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()

        result = {}
        for table_name, create_sql in tables:
            # Extract column definitions between parentheses
            fields_def = create_sql.split('(', 1)[1].rsplit(')', 1)[0]

            # this is a little janky, but the internals here aren't consistent across versions, so we eliminate some
            # characters to make it easier to compare
            fields_def = fields_def.replace('`', '').replace(')', '')

            # Parse field names from definitions
            fields = []
            for field in fields_def.split(','):
                field = field.strip()
                if field:
                    # Take first word as field name
                    field_name = field.split()[0].strip('"[]')
                    fields.append(field_name)

            result[table_name] = fields

    return result


def has_units_field(table_data: dict[str, list[str]]) -> dict[str, bool]:
    """
    determine if the table has a field for units
    :param table_data:
    :return: dictionary of table name : has units field
    """
    res = {}
    for key in table_data:
        res[key] = any('unit' in val for val in table_data[key])
    return res


def compare_tables(orig_fields: dict, other_fields: dict) -> dict[str, tuple[list[str], list[str]]]:
    """
    compare the table data from two databases and return a table-based comparison
    :param orig_fields:
    :param other_fields:
    :return: dictionary of table name : (list of fields missing in other, list of new fields in other)
    """
    res = {}
    for key in orig_fields:
        if key in other_fields:
            res[key] = (
                list(set(orig_fields[key]) - set(other_fields[key])),
                list(set(other_fields[key]) - set(orig_fields[key])),
            )
        else:
            res[key] = (orig_fields[key], [])
    return res


def compare_db_to_schema(
    db_file: Path, schema_file: Path
) -> dict[str, tuple[list[str], list[str]]]:
    """
    compare the db provided to a baseline schema and return a table-based comparison
    :param db_file: the other database
    :param schema_file: the basis of comparison
    :return: dictionary of table name : (list of fields missing in other, list of new fields in other)
    """
    td = tempfile.TemporaryDirectory()
    temp_db = Path(td.name) / 'temp.db'
    with sqlite3.connect(temp_db) as con:
        # bring in the new schema and execute
        with open(schema_file, 'r') as src:
            sql_script = src.read()
        con.executescript(sql_script)
    original_fields = table_fields(temp_db)
    other_fields = table_fields(db_file)

    return compare_tables(orig_fields=original_fields, other_fields=other_fields)


def write_comparison_md(output_file: Path, orig_schema: Path, new_db: Path):
    """write a shell of a markdown file with the comparison results"""
    comp = compare_db_to_schema(new_db, orig_schema)
    units_present = has_units_field(table_fields(new_db))
    with open(output_file, 'w') as f:
        f.write(f'## Comparison of `{new_db.name}` to schema file `{orig_schema.name}`\n')
        f.write('## Table Comparison\n')
        f.write('| Table | Missing in Other | New in Other | Units in Other DB |\n')
        f.write('|--------|-----------------|--------------|----------------|\n')
        for key in comp:
            f.write(
                f"| {key} | {comp[key][0] if comp[key][0] else ''} | {comp[key][1] if comp[key][1] else ''} | "
                f"{'yes' if units_present.get(key, False) else ''} |\n"
            )


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--db_file', help='database file to compare', action='store', dest='db_file'
    )
    parser.add_argument(
        '--schema_file', help='schema file to compare against', action='store', dest='schema_file'
    )
    args = parser.parse_args()
    res = compare_db_to_schema(Path(args.db_file), Path(args.schema_file))
    for key in res:
        if len(res[key][0]) > 0 or len(res[key][1]) > 0:
            print(f'Table {key}:')
            print(f'  Fields/descriptors missing in other: {res[key][0]}')
            print(f'  Fields/descriptors new in other: {res[key][1]}')

    output_file = Path(PROJECT_ROOT, 'output_files', 'db_schema_comparison.md')
    write_comparison_md(output_file, Path(args.schema_file), Path(args.db_file))
