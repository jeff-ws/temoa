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
Created on:  1/15/24

"""

import logging
import sqlite3
import sys
from collections import deque
from pathlib import Path
from sqlite3 import Connection
from sys import stderr as SE

import definitions
from temoa.data_processing.DB_to_Excel import make_excel
from temoa.extensions.myopic.myopic_index import MyopicIndex
from temoa.extensions.myopic.myopic_progress_mapper import MyopicProgressMapper
from temoa.temoa_model import run_actions
from temoa.temoa_model.hybrid_loader import HybridLoader
from temoa.temoa_model.model_checking.pricing_check import price_checker
from temoa.temoa_model.table_writer import TableWriter
from temoa.temoa_model.temoa_config import TemoaConfig
from temoa.temoa_model.temoa_model import TemoaModel
from temoa.temoa_model.unit_checking.screener import screen

logger = logging.getLogger(__name__)

table_script_file = Path(
    definitions.PROJECT_ROOT, 'temoa/extensions/myopic', 'make_myopic_tables.sql'
)


class MyopicSequencer:
    """
    A sequencer for solving myopic problems
    """

    # Tables that are cleaned of (scenario) data before run
    tables_with_scenario_reference = [
        'OutputBuiltCapacity',
        'OutputCost',
        'OutputCurtailment',
        'OutputDualVariable',
        'OutputEmission',
        'OutputFlowIn',
        'OutputFlowOut',
        'OutputNetCapacity',
        'OutputObjective',
        'OutputRetiredCapacity',
    ]
    tables_without_scenario_reference = [
        'MyopicEfficiency',
    ]

    # Tables that may be cleaned by period during myopic run
    # note:  below excludes MyopicEfficiency, which is managed separately

    tables_with_period = [
        'OutputCost',
        'OutputCurtailment',
        'OutputEmission',
        'OutputFlowIn',
        'OutputFlowOut',
        'OutputNetCapacity',
        'OutputRetiredCapacity',
    ]

    def __init__(self, config: TemoaConfig | None):
        self.capacity_epsilon = 1e-5
        self.debugging = False
        self.optimization_periods: list[int] | None = None
        self.instance_queue: deque[MyopicIndex] = deque()  # a LIFO queue
        self.progress_mapper: MyopicProgressMapper | None = None
        self.config = config
        # allow a "shunt" (None) here so we can test parts of this by passing a None config
        if self.config:
            self.output_con = self.get_connection()
            self.cursor = self.output_con.cursor()
            self.table_writer = TableWriter(self.config)
            # break out what is needed from the config
            myopic_options = config.myopic_inputs
            if not myopic_options:
                logger.error(
                    'The myopic mode was selected, but no options were received.\n %s',
                    config.myopic_inputs,
                )
                raise RuntimeError('No myopic options received.  See log file.')
            else:
                self.view_depth: int = myopic_options.get('view_depth')
                if not isinstance(self.view_depth, int):
                    raise ValueError(f'view_depth is not an integer {self.view_depth}')
                self.step_size: int = myopic_options.get('step_size')
                if not isinstance(self.step_size, int):
                    raise ValueError(f'step_size is not an integer {self.step_size}')
                if self.step_size > self.view_depth:
                    raise ValueError(
                        f'the Myopic step size({self.step_size}) '
                        f'is larger than the view depth ({self.view_depth}).  '
                        f'Check config'
                    )
        else:
            # A None was passed for config and the caller is responsible for setting instance vars
            pass

    def get_connection(self) -> Connection:
        """
        Get a connection to the output database
        :return: a database connection
        """
        input_file = self.config.input_database
        output_db = self.config.output_database

        if input_file.suffix not in {'.db', '.sqlite'}:
            logger.error(
                'The myopic mode processing only currently supports sourcing from a '
                'sqlite database.  Input file specified: %s',
                input_file,
            )
            raise RuntimeError('Received improper input file type.  See log file.')

        # check to see if the output_db IS the input_db, if so go forward with it.
        if input_file == output_db:
            con = sqlite3.connect(input_file)
            logger.info('Connected to database: %s', input_file)
        else:
            msg = (
                'Myopic Mode processing only supports a single database (i.e. input_file = output_db).\n'
                'This is due to the linkage between input and output and the use of Myopic tables\n'
                'in the database to orchestrate the run.  Either reset both input and output to point\n'
                'to the same db or make a copy to preserve the original and point both input/output\n'
                'to the copy.'
            )
            SE.write(msg)
            logger.error('Run aborted.  I/O database pointers are different')
            sys.exit(-1)

        return con

    def start(self):
        # run units check, if requested
        if self.config.units_check:
            # myopic requires input_db=output_db, so we can just use the input_db
            clear_screen = screen(self.config.input_database, report_path=self.config.output_path)
            if not clear_screen and not self.config.silent:
                print(
                    '\nWarning:  units screen found discrepancies.  Check log file/report for details.'
                )

        # load up the instance queue
        self.characterize_run()

        # create the Myopic Output tables, if they don't already exist.
        self.execute_script(table_script_file)

        # clear out the old riff-raff
        self.clear_old_results()

        # start building the MyopicEfficiency table.
        self.initialize_myopic_efficiency_table()

        # start the fundamental control loop
        # 1.  get feedback from previous instance execution (optimal/infeasible/...)
        # 2.  decide what to do about it
        # 3.  pull the next instance from the queue (if !empty & if needed)
        # 4.  Update the MyopicEfficiency table (clean up history / add stuff now in visibility)
        # 5.  pull data for next run and filter it with source tracing
        # 6.  build instance
        # 7.  run checks (price check) on the model, if selected
        # 8.  run the model and assess
        # 9.  commit or back out any data as necessary
        # 10.  report findings
        # 11.  compact the db

        last_instance_status = None  # solve status
        last_base_year = None
        idx: MyopicIndex | None = None  # just a type-hint
        logger.info('Starting Myopic Sequence')
        # 1, 2, 3...
        while len(self.instance_queue) > 0:
            if last_instance_status is None:
                idx = self.instance_queue.pop()
                last_base_year = idx.base_year  # starting here
            elif last_instance_status == 'optimal':
                idx = self.instance_queue.pop()
            elif last_instance_status == 'roll_back':
                curr_start_idx = self.optimization_periods.index(idx.base_year)
                new_start_idx = curr_start_idx - 1  # back up 1 increment, expanding the window
                if new_start_idx < 0:
                    logger.error('Failed myopic iteration.  Cannot back up any further.')
                    raise RuntimeError(
                        'Myopic iteration failed during attempt to back up recursively before start of optimization '
                        'period.'
                    )
                # roll back the start year by making a new index, increase the depth, keep the same last year
                base_year = self.optimization_periods[new_start_idx]
                idx = MyopicIndex(
                    base_year=base_year,
                    step_year=idx.step_year,  # no change
                    last_demand_year=idx.last_demand_year,  # no change
                    last_year=idx.last_year,  # no change
                )
            else:
                raise RuntimeError('Illegal state in myopic iteration.')
            logger.info('Processing Myopic Index: %s', idx)
            if not self.config.silent:
                self.progress_mapper.report(idx, 'load')

            # 4. update the MyopicEfficiency table so it is ready for the upcoming data pull.
            self.update_myopic_efficiency_table(myopic_index=idx, prev_base=last_base_year)

            # 5. pull the data
            # make a data loader
            data_loader = HybridLoader(self.output_con, self.config)
            data_portal = data_loader.load_data_portal(myopic_index=idx)

            # 6. build
            instance = run_actions.build_instance(
                loaded_portal=data_portal,
                model_name=self.config.scenario,
                silent=True,  # override this, we do our own reporting...
                keep_lp_file=self.config.save_lp_file,
                lp_path=self.config.output_path
                / ''.join(('LP', str(idx.base_year))),  # base year folder
            )

            # 7.  Run checks...
            if not self.config.silent:
                self.progress_mapper.report(idx, 'check')
            if self.config.price_check:
                good_prices = price_checker(instance)
                if not good_prices and not self.config.silent:
                    print('\nWarning:  Cost anomalies discovered.  Check log file for details.')

            # 8.  Run the model and assess solve status
            if not self.config.silent:
                self.progress_mapper.report(idx, 'solve')
            model, results = run_actions.solve_instance(
                instance=instance, solver_name=self.config.solver_name, silent=True
            )

            optimal, status = run_actions.check_solve_status(results)
            if not optimal:
                logger.warning('FAILED myopic iteration on %s', idx)
                logger.warning('Status: %s', status)
                last_instance_status = 'roll_back'
                # restart loop
                continue
            else:
                last_instance_status = 'optimal'

            logger.info('Completed myopic iteration on %s', idx)

            # 9, 10.  Update the output tables...
            # first, clear any possible previous results that overlap, we might have been backtracking...
            self.clear_results_after(idx.base_year)
            # add the new results...
            if not self.config.silent:
                self.progress_mapper.report(idx, 'report')
            # write results by appending.  We have already cleared necessary items
            self.table_writer.write_results(M=model, append=True)
            # handle side-case for writing duals
            if self.config.save_duals:
                self.table_writer.write_dual_variables(results=results, iteration=idx.base_year)

            # prep next loop
            last_base_year = idx.base_year  # update

            # delete anything in the OutputObjective table, it is nonsensical...
            self.output_con.execute('DELETE FROM OutputObjective WHERE 1')
            self.output_con.commit()

            # 11.  Compact the db...  lots of writes/deletes leads to bloat
            self.output_con.execute('VACUUM;')

        if self.config.save_excel:
            temp_scenario = set()
            temp_scenario.add(self.config.scenario)
            excel_filename = self.config.output_path / self.config.scenario
            make_excel(str(self.config.output_database), excel_filename, temp_scenario)

    def initialize_myopic_efficiency_table(self):
        """
        create a new MyopicEfficiency table and pre-load it with all ExistingCapacity
        :return:
        """
        # clear out everything from previous runs
        self.cursor.execute('DELETE FROM MyopicEfficiency WHERE 1')
        self.output_con.commit()

        # the -1 for base year is used to indicate "existing" for flag purposes
        # we will just use the "existing" flag in the orig db to set this up and capture
        # all values in those vintages as "existing"
        # the "coalesce" is an if-else structure to pluck out the correct lifetime value, precedence left->right
        default_lifetime = TemoaModel.default_lifetime_tech
        query = (
            'INSERT INTO MyopicEfficiency '
            '  SELECT -1, main.Efficiency.region, input_comm, Efficiency.tech, Efficiency.vintage, output_comm, efficiency, '
            f'  coalesce(main.LifetimeProcess.lifetime, main.LifetimeTech.lifetime, {default_lifetime}) AS lifetime '
            '   FROM main.Efficiency '
            '    LEFT JOIN main.LifetimeProcess '
            '       ON main.Efficiency.tech = LifetimeProcess.tech '
            '       AND main.Efficiency.vintage = LifetimeProcess.vintage '
            '       AND main.Efficiency.region = LifetimeProcess.region '
            '    LEFT JOIN main.LifetimeTech '
            '       ON main.Efficiency.tech = main.LifetimeTech.tech '
            '     AND main.Efficiency.region = main.LifeTimeTech.region '
            '   JOIN TimePeriod '
            '   ON Efficiency.vintage = TimePeriod.period '
            "   WHERE flag = 'e'"
        )

        if self.debugging:
            print(query)
        self.cursor.execute(query)
        self.output_con.commit()

        if self.debugging:
            q2 = (
                "SELECT '-1', region, input_comm, tech, vintage, output_comm, efficiency "
                'FROM Efficiency '
                '   JOIN TimePeriod '
                '   ON Efficiency.vintage = TimePeriod.period '
                "   WHERE flag = 'e'"
            )
            res = self.cursor.execute(q2).fetchall()
            print(list(res))

    def update_myopic_efficiency_table(self, myopic_index: MyopicIndex, prev_base: int):
        """
        This function adds to the MyopicEfficiency table in the db with data specific
        to the current MyopicIndex timeframe.  Basically:  prep it for the current iteration.
        :return:
        """
        # Dev Note:  The efficiency table drives the show for the model and is also used
        # internally to validate commodities, techs, etc.  So by making a period-accurate
        # efficiency table, we can bounce our other queries off of it to get accurate
        # data out of the DB, instead of dealing with it model-side

        # We already captured the ExistingCapacity efficiency values when the table
        # was initialized, so now we need to incrementally:
        # 0.  Clear from base year forward:
        #         REMOVE anything past the current base year that may have been added previously
        # 1.  Correct history from the last iteration:
        #         REMOVE things that were either:
        #           (a) NOT built at all or
        #           (b) were fully retired by the last period prior to this iteration
        #     We will use the NetCapacity to determine this
        #     NOTE:  For techs that retire, this means they won't be seen in the table at all after
        #            this iteration
        # 2.  Add the new stuff that is visible in the current myopic period

        base = myopic_index.base_year
        last_demand_year = myopic_index.last_demand_year
        logger.info('Starting update of MyopicEfficiency Table retaining [%s, %s)', prev_base, base)

        # 0.  Clear any future things past the base year for housekeeping
        #     ease with steps, depth, etc.  These may have been added if we are stepping less
        #     than the previous solve depth or if backtracking.
        self.cursor.execute(
            'DELETE FROM MyopicEfficiency WHERE MyopicEfficiency.vintage >= ?', (base,)
        )
        self.output_con.commit()

        # 1.  Clean up stuff not implemented or retired by the last time period in previous step,
        #     exempting unlim_cap techs (of course...who would forget that?)
        last_interval_end, flag = self.cursor.execute(
            'SELECT MAX(period), flag FROM main.TimePeriod WHERE period < ?',
            (myopic_index.base_year,),
        ).fetchone()
        if flag == 'f':  # the prior period should have an OutputNetCapacity entry
            # Delete anything that doesn't have capacity remaining at the end of last interval
            delete_qry = (
                'DELETE FROM MyopicEfficiency '
                'WHERE (SELECT region, tech, vintage) '
                '  NOT IN (SELECT region, tech, vintage FROM OutputNetCapacity '
                '    WHERE period = ? AND scenario = ?) '
                'AND tech not in (SELECT tech FROM Technology where unlim_cap > 0)'
            )

            if self.debugging:
                debug_query = (
                    'SELECT * FROM MyopicEfficiency '
                    'WHERE (SELECT region, tech, vintage) '
                    '  NOT IN (SELECT region, tech, vintage FROM OutputNetCapacity '
                    '    WHERE period = ? AND scenario = ?) '
                    'AND tech not in (SELECT tech FROM Technology where unlim_cap > 0)'
                )
                print('\n\n **** Removing these unused region-tech-vintage combos ****')
                removals = self.cursor.execute(
                    debug_query, (last_interval_end, self.config.scenario)
                ).fetchall()
                for i, removal in enumerate(removals):
                    print(f'{i}. Removing:  {removal}')
            self.cursor.execute(delete_qry, (last_interval_end, self.config.scenario))
            self.output_con.commit()

        # 2.  Add the new stuff now visible
        # dev note:  the `coalesce()` command is a nested if-else.  The first hit wins, so it is priority:
        #            process lifetime > tech lifetime > lifetime default
        lifetime = TemoaModel.default_lifetime_tech
        query = (
            'INSERT INTO MyopicEfficiency '
            f'SELECT {base}, Efficiency.region, input_comm, '
            '      Efficiency.tech, Efficiency.vintage, output_comm, efficiency, '
            f'     coalesce(main.LifetimeProcess.lifetime, main.LifetimeTech.lifetime, {lifetime}) '
            f'     AS lifetime '
            ' FROM main.Efficiency '
            '    LEFT JOIN main.LifetimeProcess '
            '       ON main.Efficiency.tech = LifetimeProcess.tech '
            '       AND main.Efficiency.vintage = LifetimeProcess.vintage '
            '       AND main.Efficiency.region = LifetimeProcess.region '
            '    LEFT JOIN main.LifetimeTech '
            '       ON main.Efficiency.tech = main.LifetimeTech.tech '
            '     AND main.Efficiency.region = main.LifeTimeTech.region '
            f'  WHERE Efficiency.vintage >= {base}'
            f'  AND Efficiency.vintage <= {last_demand_year}'
        )
        if self.debugging:
            # note:  the debug query below omits the lifetime computation for brevity, but is very useful without...
            raw = self.cursor.execute(
                f'SELECT {base}, region, input_comm, tech, vintage, output_comm, efficiency '
                'FROM Efficiency '
                f'  WHERE Efficiency.vintage >= {base}'
                f'  AND Efficiency.vintage <= {last_demand_year}'
            ).fetchall()
            print('\n\n **** adding to MyopicEfficiency table from newly visible techs ****')
            for idx, t in enumerate(raw):
                print(idx, t)
            print()
        self.cursor.execute(query)
        self.output_con.commit()  # MUST commit here to push the INSERTs

    def characterize_run(self, future_periods: list[int] | None = None) -> None:
        """
        inspect the db and create the MyopicIndex items
        :param future_periods: list of future period labels (years), normally None. (for test)
        :return:
        """
        if not future_periods:
            future_periods = self.cursor.execute(
                "SELECT period FROM main.TimePeriod WHERE flag = 'f'"
            ).fetchall()
            future_periods = sorted(t[0] for t in future_periods)

        # set up the progress mapper
        self.progress_mapper = MyopicProgressMapper(future_periods)
        if self.config and not self.config.silent:
            self.progress_mapper.draw_header()

        # check that we have enough periods to do myopic run
        # 2 iterations, excluding end year, will be via shortened depth, if reqd.
        if len(future_periods) < 3:
            logger.error('Not enough future years to run myopic mode: %d', len(future_periods))
            sys.exit(-1)
        self.optimization_periods = future_periods.copy()
        last_idx = len(future_periods) - 1
        for idx in range(0, len(future_periods[:-1]), self.step_size):
            depth = min(self.view_depth, last_idx - idx)
            step = min(self.step_size, last_idx - idx)
            if depth < 1:
                break
            myopic_idx = MyopicIndex(
                base_year=future_periods[idx],
                step_year=future_periods[idx + step],
                last_demand_year=future_periods[idx + depth - 1],
                last_year=future_periods[idx + depth],
            )
            self.instance_queue.appendleft(
                myopic_idx
            )  # Add to left, we will pop right, so FIFO for these
            logger.debug('Added myopic index %s', myopic_idx)
        logger.info('myopic run is divided into %d instances', len(self.instance_queue))

    def execute_script(self, script_file: Path):
        """
        A utility to execute a sql script on the current db connection
        :return:
        """
        with open(script_file, 'r') as table_script:
            sql_commands = table_script.read()
        logger.debug('Executing sql from file: %s on connection: %s', script_file, self.output_con)
        self.cursor.executescript(sql_commands)
        self.output_con.commit()

    def clear_old_results(self):
        """
        Clear old results from tables
        :return:
        """
        scenario_name = self.config.scenario
        logger.debug('Deleting old results for scenario name %s', scenario_name)
        for table in self.tables_with_scenario_reference:
            try:
                self.cursor.execute(
                    f'DELETE FROM {table} WHERE scenario = ? OR scenario like ?',
                    (scenario_name, f'{scenario_name}-%'),
                )
            except sqlite3.OperationalError:
                SE.write(f'no scenario ref in table {table}\n')
                raise sqlite3.OperationalError
        for table in self.tables_without_scenario_reference:
            try:
                self.cursor.execute(f'DELETE FROM {table} WHERE 1')
            except sqlite3.OperationalError:
                SE.write(f'Failed to clear table {table}.\n')
                raise sqlite3.OperationalError
        self.output_con.commit()

    def clear_results_after(self, period):
        """
        clear the results tables for the periods on/after the period specified
        :param period: the starting period to clear
        :return:
        """
        if period not in self.optimization_periods:
            logger.error(
                'Tried to clear period results for %s that is not in %s',
                period,
                self.optimization_periods,
            )
            raise ValueError(f'Trying to clear a year {period} that is not in the optimize periods')
        logger.debug('Clearing periods %s+ from output tables', period)

        for table in self.tables_with_period:
            try:
                self.cursor.execute(
                    f'DELETE FROM {table} WHERE period >= (?) and scenario = (?)',
                    (period, self.config.scenario),
                )
            except sqlite3.OperationalError:
                SE.write(f'Failed trying to clear periods from table {table}\n')
                raise sqlite3.OperationalError

        # special case... new capacity has vintage only...
        self.cursor.execute(
            'DELETE FROM main.OutputBuiltCapacity WHERE main.OutputBuiltCapacity.vintage >= (?) AND scenario = (?)',
            (period, self.config.scenario),
        )
        self.output_con.commit()

    def __del__(self):
        """ensure the connection is closed when destructor is called."""
        if (
            hasattr(self, 'output_con') and self.output_con is not None
        ):  # it may not be constructed yet...
            self.output_con.close()
