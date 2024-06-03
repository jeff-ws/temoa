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

This code is modified from original work on Method of Morris framework
by Hadi Eshragi.  Original morris.py file can be located in the energysystem
branch

Modified/Refactored by:  J. F. Hyink
jeff@westernspark.us
https://westernspark.us
Created on:  5/30/24

"""
import csv
import logging
import multiprocessing
import sqlite3
import tomllib
from logging.handlers import QueueListener
from multiprocessing import Queue
from pathlib import Path

from SALib.analyze import morris
from SALib.sample.morris import sample
from SALib.util import read_param_file, compute_groups_matrix
from joblib import Parallel, delayed
from numpy import array

from definitions import PROJECT_ROOT, get_OUTPUT_PATH
from temoa.extensions.method_of_morris.morris_evaluate import evaluate
from temoa.temoa_model.hybrid_loader import HybridLoader
from temoa.temoa_model.table_writer import TableWriter
from temoa.temoa_model.temoa_config import TemoaConfig

logger = logging.getLogger(__name__)

path_to_options_file = Path(PROJECT_ROOT, 'temoa/extensions/method_of_morris/solver_options.toml')


class MorrisSequencer:
    def __init__(self, config: TemoaConfig):
        self.config = config
        # PRELIMINARIES...
        # let's start with the assumption that input db = output db...  this may change?
        if not config.input_database == config.output_database:
            raise NotImplementedError('MGA assumes input and output databases are same')
        self.con = sqlite3.connect(config.input_database)

        if config.save_lp_file:
            logger.info('Saving LP file is disabled during Morris runs.')
            config.save_lp_file = False
        if config.save_duals:
            logger.info('Saving duals is disabled during Morris runs.')
            config.save_duals = False
        if config.save_excel:
            logger.info('Saving excel is disabled during Morris runs.')
            config.save_excel = False
        self.config = config

        # read in the options
        try:
            with open(path_to_options_file, 'rb') as f:
                all_options = tomllib.load(f)
            s_options = all_options.get(self.config.solver_name, {})
            logger.info('Using solver options: %s', s_options)

        except FileNotFoundError:
            logger.warning('Unable to find solver options toml file.  Using default options.')
            s_options = {}

        # get handle on solver instance
        # self.opt = pyo.SolverFactory(self.config.solver_name)
        # self.worker_solver_options = s_options

        # some defaults, etc.

        # self.num_workers = all_options.get('num_workers', 1)
        # logger.info('MGA workers are set to %s', self.num_workers)
        # self.iteration_limit = config.mga_inputs.get('iteration_limit', 20)
        # logger.info('Set MGA iteration limit to: %d', self.iteration_limit)
        # self.time_limit_hrs = config.mga_inputs.get('time_limit_hrs', 12)
        # logger.info('Set MGA time limit hours to: %0.1f', self.time_limit_hrs)
        # self.cost_epsilon = config.mga_inputs.get('cost_epsilon', 0.05)
        # logger.info('Set MGA cost (relaxation) epsilon to: %0.3f', self.cost_epsilon)

        # internal records
        self.solve_count = 0
        self.orig_label = self.config.scenario

        # output handling
        self.writer = TableWriter(self.config)
        self.writer.clear_scenario()
        self.verbose = True  # for troubleshooting
        self.mm_output_folder = get_OUTPUT_PATH() / 'MM_outputs'
        self.mm_output_folder.mkdir(exist_ok=True)
        self.param_file: Path = self.mm_output_folder / 'params.csv'

        # MM Options
        self.mm_perturbation = 0.10  # tha amount to perturb the marked params
        self.num_levels = (
            8  # the number of levels to divide the param range into (must be even number)
        )
        self.trajectories = 10  # number of morris trajectories to generate
        # Note:  Problem size (in general) is (Groups + 1) * trajectories see the SALib Dox (which aren't super)
        self.seed = 42  # for reproducible results, if desired
        logger.info('Initialized Morris sequencer')

        # hookups
        global global_con, global_config
        global_con = self.con
        global_config = self.config

    def start(self):
        """
        run the sequence of steps to do a MM analysis
        0.  clear any prior results with this scenario name.  this sequencer appends the DB, so start fresh
        1.  gather the parameters from items marked in the DB
        2.  build a data portal as a basis
        3.  use SALib to construct the sample
        :return:
        """
        # 0.  clear the scenario
        tw = TableWriter(config=self.config)
        tw.clear_scenario()

        # 1.  Gather param info from the DB and construct the param file, which will be basis of the 'problem'
        param_names = self.gather_parameters()

        # 2.  Use the loader to get raw access to the model's data (dictionary)
        loader = HybridLoader(db_connection=self.con, config=self.config)
        loader.load_data_portal()
        data = loader.data

        # 3.  Construct the MM Sample
        problem = read_param_file(str(self.param_file))
        if self.verbose:
            print(problem)
        mm_samples = sample(
            problem,
            N=self.trajectories,
            num_levels=self.num_levels,
            optimal_trajectories=False,
            local_optimization=False,
            seed=self.seed,
        )
        # 3.  Set up logging for workers
        log_queue = Queue()
        log_listener = QueueListener(log_queue, *logging.root.handlers)
        log_level = logger.getEffectiveLevel()
        log_listener.start()

        # 4.  Run the processing:
        num_cores = multiprocessing.cpu_count()
        morris_results = Parallel(n_jobs=num_cores)(
            delayed(evaluate)(
                param_names, mm_samples[i, :], data, i, self.config, log_queue, log_level
            )
            for i in range(0, len(mm_samples))
        )
        log_listener.stop()

        # 5.  Process results
        self.process_results(problem, mm_samples, morris_results)

    def process_results(self, problem, mm_sample, morris_results):
        morris_objectives = array(morris_results)
        print(morris_objectives)
        Si_OF = morris.analyze(
            problem,
            mm_sample,
            morris_objectives[:, 0],
            conf_level=0.95,
            print_to_console=False,
            num_levels=self.num_levels,
            num_resamples=1000,
            seed=self.seed + 1,
        )

        Si_CumulativeCO2 = morris.analyze(
            problem,
            mm_sample,
            morris_objectives[:, 1],
            conf_level=0.95,
            print_to_console=False,
            num_levels=self.num_levels,
            num_resamples=1000,
            seed=self.seed + 2,
        )
        groups, unique_group_names = compute_groups_matrix(problem['groups'])
        number_of_groups = len(unique_group_names)
        print(
            '{0:<30} {1:>10} {2:>10} {3:>15} {4:>10}'.format(
                'Parameter', 'Mu_Star', 'Mu', 'Mu_Star_Conf', 'Sigma'
            )
        )
        for j in list(range(number_of_groups)):
            print(
                '{0:30} {1:10.3f} {2:10.3f} {3:15.3f} {4:10.3f}'.format(
                    Si_OF['names'][j],
                    Si_OF['mu_star'][j],
                    Si_OF['mu'][j],
                    Si_OF['mu_star_conf'][j],
                    Si_OF['sigma'][j],
                )
            )

        line1 = Si_OF['mu_star']
        line2 = Si_OF['mu_star_conf']
        line3 = Si_CumulativeCO2['mu_star']
        line4 = Si_CumulativeCO2['mu_star_conf']
        with open('MMResults.csv', 'w') as f:
            writer = csv.writer(f, delimiter=',')
            writer.writerow(unique_group_names)
            writer.writerow(b'Objective Function')
            writer.writerow(line1)
            writer.writerow(line2)
            writer.writerow(b'Cumulative CO2 Emissions')
            writer.writerow(line3)
            writer.writerow(line4)
        f.close()

    def gather_parameters(self):
        """
        Scan the annotated DB tables for marked parameters and capture them
        in the parameters file.  Also capture the names in the param_info data
        structure for use in pulling data
        """
        # TODO:  Consider hijacking the iter entry below, which is the 'name' when problem is created to
        #        contain the db descriptor to alleviate need for the param_info dict?
        param_names = {}
        cur = self.con.cursor()
        with open(self.param_file, 'w') as f:
            v_idx = 4  # index of variable to perturb
            raw = cur.execute(
                'SELECT region, period, tech, vintage, cost, MMAnalysis FROM CostVariable WHERE MMAnalysis IS NOT NULL'
            ).fetchall()
            g1 = len(raw)
            for i in range(0, len(raw)):
                param_names[i] = [
                    'CostVariable',
                    *raw[i][:4],
                    'cost_variable',
                ]
                iter = f'x{i}'
                low = str(raw[i][v_idx] * (1 - self.mm_perturbation))
                high = str(raw[i][v_idx] * (1 + self.mm_perturbation))
                mm_name = raw[i][-1]

                row = ','.join((iter, low, high, mm_name))
                f.write(row + '\n')

            v_idx = 3
            raw = cur.execute(
                'SELECT region, tech, vintage, cost, MMAnalysis FROM CostInvest WHERE MMAnalysis IS NOT NULL'
            ).fetchall()
            g2 = len(raw)
            for i in range(0, len(raw)):
                param_names[i + g1] = ['CostInvest', *raw[i][:3], 'cost_invest']

                iter = f'x{i + g1}'
                low = str(raw[i][v_idx] * (1 - self.mm_perturbation))
                high = str(raw[i][v_idx] * (1 + self.mm_perturbation))
                mm_name = raw[i][-1]

                row = ','.join((iter, low, high, mm_name))
                f.write(row + '\n')

            v_idx = 5
            raw = cur.execute(
                'SELECT DISTINCT region, input_comm, tech, vintage, output_comm, efficiency, '
                'MMAnalysis FROM Efficiency WHERE MMAnalysis IS NOT NULL'
            ).fetchall()

            g3 = len(raw)
            for i in range(0, len(raw)):
                param_names[i + g1 + g2] = [
                    'Efficiency',
                    *raw[i][:5],
                    'efficiency',
                ]

                iter = f'x{i + g1 + g2}'
                low = str(raw[i][v_idx] * (1 - self.mm_perturbation))
                high = str(raw[i][v_idx] * (1 + self.mm_perturbation))
                mm_name = raw[i][-1]

                row = ','.join((iter, low, high, mm_name))
                f.write(row + '\n')
        # check for empty (no marked params)
        if sum((g1, g2, g3)) == 0:
            logger.error('No parameters marked for MM analysis')
            raise ValueError('No parameters marked for MM analysis')

        return param_names

    def __del__(self):
        self.con.close()
