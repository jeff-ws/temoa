"""
The Temoa Sequencer's job is to sequence the actions needed to execute a scenario.  Each
scenario has a declared processing mode (regular, myopic, mga, etc.) and the Temoa Sequencer sets
up the necessary run(s) to accomplish that.  Several processing modes have requirements
for multiple runs, and the Temoa Sequencer may hand off to a mode-specific sequencer

Written by:  J. F. Hyink
jeff@westernspark.us
https://westernspark.us
Created on:  11/14/23

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
"""
import sqlite3
import sys
from logging import getLogger
from pathlib import Path

import pyomo.opt

from temoa.temoa_model import source_check
from temoa.temoa_model.myopic.hybrid_loader import HybridLoader
from temoa.temoa_model.myopic.myopic_sequencer import MyopicSequencer
from temoa.temoa_model.pricing_check import price_checker
from temoa.temoa_model.run_actions import (
    build_instance,
    solve_instance,
    handle_results,
    check_solve_status,
)
from temoa.temoa_model.source_check import source_trace
from temoa.temoa_model.table_writer import TableWriter
from temoa.temoa_model.temoa_config import TemoaConfig
from temoa.temoa_model.temoa_mode import TemoaMode
from temoa.temoa_model.temoa_model import TemoaModel
from temoa.temoa_model.temoa_run import temoa_checks

logger = getLogger(__name__)


class TemoaSequencer:
    """A Sequencer instance to control all runs for a scenario based on the TemoaMode"""

    def __init__(
        self,
        config_file: str | Path,
        output_path: str | Path,
        mode_override: TemoaMode | None = None,
        silent: bool = False,
        **kwargs,
    ):
        """
        Create a new Sequencer
        :param config_file: Optional path to config file.  If not provided, it will be read
        from Command Line Args
        :param mode_override: Optional override to execution mode.  If not provided,
        it will be read from config file
        :param silent:  boolean to indicate whether to silence run-time feedback
        """
        self.config: TemoaConfig | None = None
        self.temoa_mode: TemoaMode

        self.config_file: Path = Path(config_file)
        # check it...
        if not self.config_file.is_file():
            logger.error(
                'Config file location passed %s does not point to a file', self.config_file
            )
            raise FileNotFoundError(f'Invalid config file: {self.config_file}')

        self.output_path: Path = Path(output_path)
        # check it...
        if not self.output_path.is_dir():
            logger.error('Output directory does not exist: %s', self.output_path)
            raise FileNotFoundError(f'Invalid output directory: {self.output_path}')

        self.temoa_mode: TemoaMode = TemoaMode.BUILD_ONLY  # placeholder, over-written in start()
        self.mode_override: TemoaMode = mode_override

        # for feedback to user
        self.silent = silent

        # for results catching for perfect_foresight / testing
        self.pf_results: pyomo.opt.SolverResults | None = None
        self.pf_solved_instance: TemoaModel | None = None

    def start(self) -> TemoaModel | None:
        """Start the processing of the scenario"""

        # Run the preliminaries...
        # Build a TemoaConfig
        self.config = TemoaConfig.build_config(
            config_file=self.config_file, output_path=self.output_path, silent=self.silent
        )

        # TODO:  Screen this vs. what is already done at this point
        temoa_checks(self.config)

        # Distill the TemoaMode
        # self.temoa_mode = self.mode_override if self.mode_override else self.config.scenario_mode
        if self.mode_override and self.mode_override != self.config.scenario_mode:
            # capture and log the override...
            self.temoa_mode = self.mode_override
            logger.info('Temoa Mode overridden to be:  %s', self.temoa_mode)
        else:
            self.temoa_mode = self.config.scenario_mode
        # check it...
        if not isinstance(self.temoa_mode, TemoaMode):
            logger.error(
                'Temoa Mode not set properly.  Override: %d, Config File: %d',
                self.mode_override,
                self.config.scenario_mode,
            )
            raise RuntimeError('Problem with mode selection, see log file.')

        # Get user confirmation if not silent
        if not self.silent:
            try:
                print(self.config.__repr__())
                print('\nPlease press enter to continue or Ctrl+C to quit.\n')
                input()  # Give the user a chance to confirm input
            except KeyboardInterrupt:
                logger.warning('User aborted from confirmation page.  Exiting')
                print('\n\nUser requested quit.  Exiting Temoa ...\n')
                sys.exit()

        # Select execution path based on mode
        match self.temoa_mode:
            case TemoaMode.BUILD_ONLY:
                # convert the input file from .sqlite -> .dat if needed
                # if self.config.input_file.suffix == '.sqlite':
                #     dat_file = self.config.input_file.with_suffix('.dat')
                #     db_2_dat(self.config.input_file, dat_file, self.config)
                #     # update the config to point to the .dat file newly created
                #     self.config.dat_file = dat_file
                # data_portal: DataPortal = load_portal_from_dat(self.config.dat_file, silent=self.config.silent)
                # TODO:  This connection should probably be made in the loader?
                con = sqlite3.connect(self.config.input_file)
                hybrid_loader = HybridLoader(db_connection=con)
                data_portal = hybrid_loader.load_data_portal(myopic_index=None)
                instance = build_instance(data_portal, silent=self.config.silent)
                return instance

            case TemoaMode.CHECK:
                # TODO:  This connection should probably be made in the loader?
                con = sqlite3.connect(self.config.input_file)
                hybrid_loader = HybridLoader(db_connection=con)
                data_portal = hybrid_loader.load_data_portal(myopic_index=None)

                instance = build_instance(data_portal, silent=self.config.silent)
                # disregard what the config says about price_check and source_check and just do it...
                price_checker(instance)
                source_trace(instance, temoa_config=self.config)

            case TemoaMode.PERFECT_FORESIGHT:
                con = sqlite3.connect(self.config.input_file)
                hybrid_loader = HybridLoader(db_connection=con)
                data_portal = hybrid_loader.load_data_portal(myopic_index=None)
                instance = build_instance(data_portal, silent=self.config.silent)
                if self.config.price_check:
                    price_checker(instance)
                if self.config.source_check:
                    source_check.source_trace(instance, temoa_config=self.config)
                self.pf_solved_instance, self.pf_results = solve_instance(
                    instance,
                    self.config.solver_name,
                    self.config.save_lp_file,
                    silent=self.config.silent,
                )
                good_solve, msg = check_solve_status(self.pf_results)
                if not good_solve:
                    logger.error('The solve result is reported as %s.  Aborting', msg)
                    logger.error(
                        'This may be the result of the output messaging of the chosen solver'
                        'If this is deemed an acceptable status, adjustment may be needed to the '
                        'function check_solve_status in run_actions.py'
                    )
                    sys.exit(-1)
                handle_results(self.pf_solved_instance, self.pf_results, self.config)
                table_writer = TableWriter(self.config, con)
                table_writer.write_costs(instance)

            case TemoaMode.MYOPIC:
                # create a myopic sequencer and shift control to it
                myopic_sequencer = MyopicSequencer(config=self.config)
                myopic_sequencer.start()
            case _:
                raise NotImplementedError('not yet built')