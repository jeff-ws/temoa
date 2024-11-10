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
Created on:  11/9/24

A sequencer for Monte Carlo Runs
.
"""
import sqlite3
from datetime import datetime

from temoa.extensions.monte_carlo.mc_run import MCRun
from temoa.temoa_model.hybrid_loader import HybridLoader
from temoa.temoa_model.table_writer import TableWriter
from temoa.temoa_model.temoa_config import TemoaConfig


class MCSequencer:
    """
    A sequencer to control the steps in Monte Carlo run sequence
    """

    def __init__(self, config: TemoaConfig):
        self.config = config

        # internal records
        self.solve_count = 0
        self.seen_instance_indices = set()
        self.orig_label = self.config.scenario

        # output handling
        self.writer = TableWriter(self.config)
        self.writer.clear_scenario()
        self.verbose = False  # for troubleshooting

    def start(self):
        """Run the sequencer"""
        # ==== basic sequence ====
        # 1. Load the model data, which may involve filtering it down if source tracing
        # 2. run a quick screen on the inputs using the data above as part of the screen
        #    before starting the long run
        # 3. make a queue for runs
        # 4. copy & modify the base data to make per-dataset runs
        # 5. farm out the runs to workers

        start_time = datetime.now()

        # 1. Load data
        with sqlite3.connect(self.config.input_database) as con:
            hybrid_loader = HybridLoader(db_connection=con, config=self.config)
        data_store = hybrid_loader.create_data_dict(myopic_index=None)
        mc_run = MCRun(config=self.config, data_store=data_store)

        # 2. Screen the input file
        mc_run.prescreen_input_file()

        # 3. check runs
        run_gen = mc_run.run_generator()
        for run in run_gen:
            print(run)

        # data_portal: DataPortal = hybrid_loader.load_data_portal(myopic_index=None)
        # instance: TemoaModel = build_instance(
        #     loaded_portal=data_portal, model_name=self.config.scenario, silent=self.config.silent
        # )
        # if self.config.price_check:
        #     good_prices = price_checker(instance)
        #     if not good_prices and not self.config.silent:
        #         print('Warning:  Cost anomalies discovered.  Check log file for details.')
        # # tag the instance by name, so we can sort out the multiple results...
        # instance.name = '-'.join((self.config.scenario, '0'))
        #
        # # 2. Base solve
        # tic = datetime.now()
        # #   ============ First Solve ============
        # #  Note:  We *exclude* the worker_solver_options here to get a more precise base cost
        # res: Results = self.opt.solve(instance)
        # toc = datetime.now()
        # elapsed = toc - tic
        # self.solve_count += 1
        # logger.info(f'Initial solve time: {elapsed.total_seconds():.4f}')
        # status = res.solver.termination_condition
        # logger.debug('Termination condition: %s', status.name)
        # if not check_optimal_termination(res):
        #     logger.error('The baseline MGA solve failed.  Terminating run.')
        #     raise RuntimeError('Baseline MGA solve failed.  Terminating run.')
        #
        # # record the 0-solve in all tables
        # self.writer.write_results(instance, iteration=0)
        # self.writer.make_summary_flow_table()  # make the flow summary table, if it doesn't exist
        # self.writer.write_summary_flow(instance, iteration=0)
