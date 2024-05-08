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
Created on:  4/15/24

The purpose of this module is to perform top-level control over an MGA model run
"""
import logging
import queue
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from logging import getLogger
from multiprocessing import Queue
from queue import Empty

import pyomo.contrib.appsi as pyomo_appsi
import pyomo.environ as pyo
from pyomo.contrib.appsi.base import Results
from pyomo.core import Expression
from pyomo.dataportal import DataPortal

# from temoa.extensions.modeling_to_generate_alternatives.worker import Worker
from temoa.extensions.modeling_to_generate_alternatives.manager_factory import get_manager
from temoa.extensions.modeling_to_generate_alternatives.mga_constants import MgaAxis, MgaWeighting
from temoa.extensions.modeling_to_generate_alternatives.vector_manager import VectorManager
from temoa.extensions.modeling_to_generate_alternatives.worker import Worker
from temoa.temoa_model.hybrid_loader import HybridLoader
from temoa.temoa_model.run_actions import build_instance
from temoa.temoa_model.table_writer import TableWriter
from temoa.temoa_model.temoa_config import TemoaConfig
from temoa.temoa_model.temoa_model import TemoaModel
from temoa.temoa_model.temoa_rules import TotalCost_rule

logger = getLogger(__name__)


class MgaSequencer:
    def __init__(self, config: TemoaConfig):
        # PRELIMINARIES...
        # let's start with the assumption that input db = output db...  this may change?
        if not config.input_database == config.output_database:
            raise NotImplementedError('MGA assumes input and output databases are same')
        self.con = sqlite3.connect(config.input_database)

        if not config.source_trace:
            logger.warning(
                'Performing MGA runs without source trace.  '
                'Recommend selecting source trace in config file.'
            )
        if config.save_lp_file:
            logger.info('Saving LP file is disabled during MGA runs.')
            config.save_lp_file = False
        if config.save_duals:
            logger.info('Saving duals is disabled during MGA runs.')
            config.save_duals = False
        if config.save_excel:
            logger.info('Saving excel is disabled during MGA runs.')
            config.save_excel = False
        self.config = config

        # get handle on solver instance
        # TODO:  Check that solver is a persistent solver
        if self.config.solver_name == 'appsi_highs':
            self.opt = pyomo_appsi.solvers.highs.Highs()
            self.std_opt = pyo.SolverFactory('appsi_highs')
        elif self.config.solver_name == 'gurobi':
            # self.opt = pyomo_appsi.solvers.Gurobi()
            self.opt = pyo.SolverFactory('gurobi')
            # self.options = {
            #     # 'LogFile': './my_gurobi_log.log',
            #     'LPWarmStart': 2,  # pass basis
            #     'TimeLimit': 3600 * 4,  # seconds = 4hr
            #     'FeasibilityTol': 1e-4,  # default = 1e-6, we only need 'rough' solutions
            #     # 'Crossover': 0,  # disabled
            #     # 'Method': 2,  # Barrier ONLY
            # }
            self.options = {
                'Method': 2,  # Barrier ONLY
                'Threads': 30,
                'FeasibilityTol': 1e-3,  # pretty 'loose'
                'Crossover': 0,  # Disabled
                'TimeLimit': 3600 * 3,  # 3 hrs
            }
            self.opt.gurobi_options = self.options
        elif self.config.solver_name == 'cbc':
            self.opt = pyo.SolverFactory('cbc')
            self.options = {}

        # some defaults, etc.
        self.internal_stop = False
        self.mga_axis = config.mga_inputs.get('axis')
        if not self.mga_axis:
            logger.warning('No MGA Axis specified.  Using default:  Activity by Tech Category')
            self.mga_axis = MgaAxis.TECH_CATEGORY_ACTIVITY

        self.mga_weighting = config.mga_inputs.get('weighting')
        if not self.mga_weighting:
            logger.warning('No MGA Weighting specified.  Using default: Hull Expansion')
            self.mga_weighting = MgaWeighting.HULL_EXPANSION
        self.iteration_limit = config.mga_inputs.get('iteration_limit', 20)
        self.time_limit_hrs = config.mga_inputs.get('time_limit_hrs', 12)
        self.cost_epsilon = config.mga_inputs.get('cost_epsilon', 0.05)

        # internal records
        self.solve_records: list[tuple[Expression, Sequence[float]]] = []
        """(solve vector, resulting axis vector)"""
        self.solve_count = 0
        self.orig_label = self.config.scenario

        # output handling
        self.writer = TableWriter(self.config)
        self.writer.clear_indexed_scenarios()

        logger.info(
            'Initialized MGA sequencer with MGA Axis %s and weighting %s',
            self.mga_axis.name,
            self.mga_weighting.name,
        )

    def start(self):
        """Run the sequencer"""
        # ==== basic sequence ====
        # 1. Load the model data, which may involve filtering it down if source tracing
        # 2. Solve the base model (using persistent solver...maybe)
        # 3. Adjust the model
        # 4. Instantiate a Vector Manager pull in extra data to build out data for axis
        # 5. Start the re-solve loop

        # 1. Load data
        hybrid_loader = HybridLoader(db_connection=self.con, config=self.config)
        data_portal: DataPortal = hybrid_loader.load_data_portal(myopic_index=None)
        instance: TemoaModel = build_instance(
            loaded_portal=data_portal, model_name=self.config.scenario, silent=self.config.silent
        )

        # 2. Base solve
        tic = datetime.now()
        # ============ First Solve ============
        res: Results = self.opt.solve(instance)
        toc = datetime.now()
        # load variables after first solve
        # self.opt.load_vars()
        elapsed = toc - tic
        self.solve_count += 1
        logger.info(f'Initial solve time: {elapsed.total_seconds():.4f}')
        status = res.solver.termination_condition

        logger.debug('Termination condition: %s', status.name)
        # if status != pyomo_appsi.base.TerminationCondition.optimal:
        #     logger.error('Abnormal termination condition on baseline solve')
        #     sys.exit(-1)
        # record the 0-solve in all tables
        self.writer.write_results(instance)

        # 3a. Capture cost and make it a constraint
        tot_cost = pyo.value(instance.TotalCost)
        logger.info('Completed initial solve with total cost:  %0.2f', tot_cost)
        logger.info('Relaxing cost by fraction:  %0.3f', self.cost_epsilon)
        # get hook on the expression generator for total cost...
        cost_expression = TotalCost_rule(instance)
        instance.cost_cap = pyo.Constraint(
            expr=cost_expression <= (1 + self.cost_epsilon) * tot_cost
        )
        # self.opt.add_constraints([instance.cost_cap])

        # 3b. replace the objective and prep for iterative solving
        instance.del_component(instance.TotalCost)
        # instance.TotalCost.deactivate()
        # self.opt.set_instance(instance)
        # self.opt.config.load_solution = False

        # 4.  Instantiate the vector manager
        vector_manager: VectorManager = get_manager(
            axis=self.mga_axis,
            model=instance,
            weighting=self.mga_weighting,
            con=self.con,
            optimal_cost=tot_cost,
            cost_relaxation=self.cost_epsilon,
        )

        # 5.  Set up the Workers

        work_queue = Queue(5)  # restrict the queue to hold just 2 models in it max
        result_queue = Queue(5)
        log_queue = Queue(50)
        # start the logging listener
        # listener = Process(target=listener_process, args=(log_queue,))
        # listener.start()
        # make workers
        workers = []
        kwargs = {'solver_name': self.config.solver_name, 'solver_options': self.options}
        num_workers = 6
        for i in range(num_workers):
            w = Worker(
                model_queue=work_queue,
                results_queue=result_queue,
                configurer=None,  # worker.worker_configurer,
                log_root_name=__name__,
                log_queue=log_queue,
                log_level=logging.INFO,
                **kwargs,
            )
            w.start()
            workers.append(w)
        # workers now running and waiting for jobs...

        # 6.  Start the iterative solve process and let the manager run the show
        instance_generator = vector_manager.instance_generator(self.config)
        instance = next(instance_generator)
        while not vector_manager.stop_resolving() and not self.internal_stop:
            # print(
            #     f'iter {self.solve_count}:',
            #     f'vecs_avail: {vector_manager.input_vectors_available()}',
            # )
            logger.info('Putting an instance in the work queue')
            try:
                if instance != 'waiting':  # sentinel for waiting for more solves to be done
                    # print('trying to load work queue')
                    work_queue.put(instance, block=False)  # put a log on the fire, if room
                    instance = next(instance_generator)
            except queue.Full:
                print('work queue is full')
                pass
            try:
                next_result = result_queue.get()
            except Empty:
                next_result = None
            if next_result is not None:
                vector_manager.process_results(M=next_result)
                self.process_solve_results(next_result)

                self.solve_count += 1
                print(self.solve_count)
                if self.solve_count >= self.iteration_limit:
                    self.internal_stop = True

        # 7. Shut down the workers and then the logging queue
        print('shutting it down')
        for w in workers:
            work_queue.put(None)
        # print(f'work queue: {work_queue.qsize()}')
        # print(f'result queue size: {result_queue.qsize()}')
        # try flushing queues
        # try:
        #     while True:
        #         work_queue.get_nowait()
        #         print('popped work queue')
        # except queue.Empty:
        #     pass
        # try:
        #     while True:
        #         result_queue.get_nowait()
        #         print('popped result queue')
        # except queue.Empty:
        #     pass
        # try:
        #     while True:
        #         log_queue.get_nowait()
        # except queue.Empty:
        #     log_queue.close()

        for w in workers:
            print(w.worker_number, w.is_alive())
        for w in workers:
            w.join()
            print('worker wrapped up...')
        for w in workers:
            print(w.worker_number, w.is_alive())
        # log_queue.put_nowait(None)  # sentinel to shut down the log listener
        log_queue.close()
        # log_queue.join_thread()
        print('log queue closed')
        work_queue.close()
        # work_queue.join_thread()
        print('work queue joined')
        result_queue.close()
        # result_queue.join_thread()
        print('result queue joined')
        # listener.join()

        # 8. Wrap it up
        vector_manager.finalize_tracker()

    def solve_instance(self, instance: TemoaModel) -> bool:
        # instance.obj = pyo.Objective(expr=vector)
        # self.opt.set_objective(instance.obj)
        # instance.obj.display()
        tic = datetime.now()
        res = self.opt.solve(instance)
        toc = datetime.now()
        elapsed = toc - tic
        # status = res.termination_condition
        status = res['Solver'].termination_condition
        logger.info(
            'Solve #%d time: %0.4f.  Status: %s',
            self.solve_count,
            elapsed.total_seconds(),
            status.name,
        )
        # need to load vars here else we see repeated stale value of objective
        return status == pyo.TerminationCondition.optimal

    def solve_instance_appsi(self, instance) -> bool:
        """
        Solve the MGA instance
        :param instance: the model instance
        :return: True if solve was successful, False otherwise
        """
        tic = datetime.now()
        res = self.opt.solve(instance)
        toc = datetime.now()
        elapsed = toc - tic
        status = res.termination_condition
        logger.info(
            'Solve #%d time: %0.4f.  Status: %s',
            self.solve_count,
            elapsed.total_seconds(),
            status.name,
        )
        # need to load vars here else we see repeated stale value of objective
        if res.termination_condition == pyomo_appsi.base.TerminationCondition.optimal:
            self.opt.load_vars()
        return res.termination_condition == pyomo_appsi.base.TerminationCondition.optimal

    def process_solve_results(self, instance):
        # cheap label...
        self.writer.write_capacity_tables(M=instance, iteration=self.solve_count)

    def __del__(self):
        self.con.close()


# def listener_configurer():
#     root = logging.getLogger()
#     h = logging.handlers.RotatingFileHandler('mptest.log', 'a', 300, 10)
#     f = logging.Formatter('%(asctime)s %(processName)-10s %(name)s %(levelname)-8s %(message)s')
#     h.setFormatter(f)
#     root.addHandler(h)


# This is the listener process top-level loop: wait for logging events
# (LogRecords)on the queue and handle them, quit when you get a None for a
# LogRecord.
def listener_process(queue):
    # configurer()
    while True:
        try:
            record = queue.get(timeout=5)
            print('bagged a message from the queue')
            if record is None:  # We send this as a sentinel to tell the listener to quit.
                break
            logger = logging.getLogger(record.name)
            logger.handle(record)  # No level or filter logic applied - just do it!
        except Empty:
            pass
        except Exception:
            import sys, traceback

            print('Whoops! Problem:', file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
