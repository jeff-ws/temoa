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
in LICENSE.txt.  Users expanding this from an archive may not have
received this license file.  If not, see <http://www.gnu.org/licenses/>.
"""

import tomllib
from logging import getLogger
from pathlib import Path
from sys import stderr as SE

from temoa.temoa_model.temoa_mode import TemoaMode

logger = getLogger(__name__)


class TemoaConfig:
    """
    The overall configuration for a Temoa Scenario
    """

    def __init__(
        self,
        scenario: str,
        scenario_mode: TemoaMode | str,
        input_database: Path,
        output_database: Path,
        output_path: Path,
        solver_name: str,
        neos: bool = False,
        save_excel: bool = False,
        save_duals: bool = False,
        save_lp_file: bool = False,
        MGA: dict | None = None,
        myopic: dict | None = None,
        config_file: Path | None = None,
        silent: bool = False,
        stream_output: bool = False,
        price_check: bool = True,
        source_trace: bool = False,
        plot_commodity_network: bool = False,
    ):
        self.scenario = scenario
        # capture the operating mode
        self.scenario_mode: TemoaMode
        match scenario_mode:
            case TemoaMode():
                self.scenario_mode = scenario_mode
            case str():
                try:
                    self.scenario_mode = TemoaMode[scenario_mode.upper()]
                except KeyError:
                    raise AttributeError(
                        f'The mode selection received by TemoaConfig: '
                        f'{scenario_mode} is invalid.\nPossible choices are '
                        f'{list(TemoaMode.__members__.keys())} (case '
                        f'insensitive).'
                    )
            case _:
                raise AttributeError(
                    f'The mode selection received by TemoaConfig: '
                    f'{scenario_mode} is invalid.\nPossible choices are '
                    f'{list(TemoaMode.__members__.keys())} (case '
                    f'insensitive).'
                )

        self.config_file = config_file

        # accept and screen the input file
        self.input_database = Path(input_database)
        if not self.input_database.is_file():
            raise FileNotFoundError(f'could not locate the input database: {self.input_database}')
        if self.input_database.suffix not in {'.db', '.sqlite'}:
            logger.error('Input file is not of type .ddb or .sqlite')
            raise AttributeError('Input file is not of type .db or .sqlite')

        # accept and validate the output db
        self.output_database = Path(output_database)
        if not self.output_database.is_file():
            raise FileNotFoundError(f'Could not locate the output db: {self.output_database}')
        if self.output_database.suffix != '.sqlite':
            logger.error('Output DB does not appear to be a sqlite db')
            raise AttributeError('Output DB should be .sqlite type')

        # create a placeholder for .dat file.  If conversion is needed, this
        # is the destination...
        self.dat_file: Path | None = None

        self.output_path = output_path
        self.neos = neos
        if self.neos:
            raise NotImplementedError('Neos is currently not supported.')

        self.solver_name = solver_name
        self.save_excel = save_excel
        self.save_duals = save_duals
        self.save_lp_file = save_lp_file

        self.mga_inputs = MGA
        self.myopic_inputs = myopic
        self.silent = silent
        self.stream_output = stream_output
        self.price_check = price_check
        self.source_trace = source_trace
        if plot_commodity_network and not self.source_trace:
            logger.warning(
                'Commodity Network plotting was selected, but Source Trace was not selected.  '
                'Both are required to produce plots.'
            )
        self.plot_commodity_network = plot_commodity_network and self.source_trace

        # warn if output db != input db
        if self.input_database.suffix == self.output_database.suffix:  # they are both .db/.sqlite
            if self.input_database != self.output_database:  # they are not the same db
                msg = (
                    'Input file, which is a database, does not match the output file\n User '
                    'is responsible to ensure the data ~ results congruency in the output db'
                )
                logger.warning(msg)
                if not self.silent:
                    SE.write('Warning: ' + msg)

    @staticmethod
    def validate_schema(data: dict):
        """
        Validate the schema against what is expected in init
        :return: None
        """
        # dev note:  we can use match statement to compare the schema to a structural pattern.
        #            This does not provide great feedback.  If it gets more complicated, a shift
        #            to Pydantic would be in order.
        match data:
            case {
                'scenario': str(),
                'scenario_mode': str(),
                'input_database': str(),
                'output_database': str(),
                'neos': bool(),
                'solver_name': str(),
                'save_excel': bool(),
                'save_duals': bool(),
                'save_lp_file': bool(),
                'MGA': {'slack': int(), 'iterations': int(), 'weight': str()},
                'myopic': {'myopic_view': int(), 'keep_myopic_databases': bool()},
                'price_check': bool(),
                'source_trace': bool(),
                'plot_commodity_network': bool(),
            }:
                # full schema OK
                pass
            case {
                'scenario': str(),
                'scenario_mode': str(),
                'input_database': str(),
                'output_database': str(),
                'solver_name': str(),
                'save_excel': bool(),
            }:
                # ALL optional args omitted, OK
                pass
            case _:
                # didn't match
                raise ValueError(
                    'Schema received from TOML is not correct.  x-check field names '
                    'and values with example'
                )

    @staticmethod
    def build_config(config_file: Path, output_path: Path, silent=False) -> 'TemoaConfig':
        """
        build a Temoa Config from a config file
        :param silent: suppress warnings and confirmations
        :param output_path:
        :param config_file: the path to the config file to use
        :return: a TemoaConfig instance
        """
        with open(config_file, 'rb') as f:
            data = tomllib.load(f)
        TemoaConfig.validate_schema(data=data)
        tc = TemoaConfig(output_path=output_path, config_file=config_file, silent=silent, **data)
        logger.info('Scenario Name:  %s', tc.scenario)
        logger.info('Data source:  %s', tc.input_database)
        logger.info('Data target:  %s', tc.output_database)
        logger.info('Mode:  %s', tc.scenario_mode.name)
        return tc

    def __repr__(self):
        width = 25
        spacer = '\n' + '-' * width + '\n'
        msg = spacer
        # for i in self.dot_dat:
        #     if self.dot_dat.index(i) == 0:
        #         msg += '{:>{}s}: {}\n'.format('Input file', width, i)
        #     else:
        #         msg += '{:>25s}  {}\n'.format(' ', i)
        msg += '{:>{}s}: {}\n'.format('Scenario', width, self.scenario)
        msg += '{:>{}s}: {}\n'.format('Scenario mode', width, self.scenario_mode.name)
        msg += '{:>{}s}: {}\n'.format('Config file', width, self.config_file)
        msg += '{:>{}s}: {}\n'.format('Data source', width, self.input_database)
        msg += '{:>{}s}: {}\n'.format('Output database target', width, self.output_database)
        msg += '{:>{}s}: {}\n'.format('Path for outputs and log', width, self.output_path)

        msg += spacer
        msg += '{:>{}s}: {}\n'.format('Price check', width, self.price_check)
        msg += '{:>{}s}: {}\n'.format('Source trace', width, self.source_trace)
        msg += '{:>{}s}: {}\n'.format('Commodity network plots', width, self.plot_commodity_network)

        msg += spacer
        msg += '{:>{}s}: {}\n'.format('Selected solver', width, self.solver_name)
        msg += '{:>{}s}: {}\n'.format('NEOS status', width, self.neos)

        msg += spacer
        msg += '{:>{}s}: {}\n'.format('Spreadsheet output', width, self.save_excel)
        msg += '{:>{}s}: {}\n'.format('Pyomo LP write status', width, self.save_lp_file)
        msg += '{:>{}s}: {}\n'.format('Save duals to output db', width, self.save_duals)

        # TODO:  conditionally add in the mode options

        if self.scenario_mode == TemoaMode.MYOPIC:
            msg += spacer
            msg += '{:>{}s}: {}\n'.format(
                'Myopic view depth', width, self.myopic_inputs.get('view_depth')
            )
            msg += '{:>{}s}: {}\n'.format(
                'Myopic step size', width, self.myopic_inputs.get('step_size')
            )

        # msg += '{:>{}s}: {}\n'.format('Retain myopic databases', width, self.KeepMyopicDBs)
        # msg += spacer
        # msg += '{:>{}s}: {}\n'.format('Citation output status', width, self.how_to_cite)
        # msg += '{:>{}s}: {}\n'.format('Version output status', width, self.version)
        # msg += spacer
        # msg += '{:>{}s}: {}\n'.format('Solver LP write status', width, self.generateSolverLP)
        # msg += spacer
        # msg += '{:>{}s}: {}\n'.format('MGA slack value', width, self.mga)
        # msg += '{:>{}s}: {}\n'.format('MGA # of iterations', width, self.mga_iter)
        # msg += '{:>{}s}: {}\n'.format('MGA weighting method', width, self.mga_weight)
        # msg += '**NOTE: If you are performing MGA runs, navigate to the DAT file and make
        # any modifications to the MGA sets before proceeding.'
        return msg
