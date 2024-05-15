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
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from logging import getLogger

import pyomo.contrib.appsi as pyomo_appsi
import pyomo.environ as pyo
from deprecated.classic import deprecated
from pyomo.contrib.appsi.base import Results
from pyomo.core import Expression
from pyomo.dataportal import DataPortal

from temoa.extensions.modeling_to_generate_alternatives.manager_factory import get_manager
from temoa.extensions.modeling_to_generate_alternatives.mga_constants import MgaAxis, MgaWeighting
from temoa.extensions.modeling_to_generate_alternatives.vector_manager import VectorManager
from temoa.temoa_model.hybrid_loader import HybridLoader
from temoa.temoa_model.run_actions import build_instance
from temoa.temoa_model.temoa_config import TemoaConfig
from temoa.temoa_model.temoa_model import TemoaModel
from temoa.temoa_model.temoa_rules import TotalCost_rule

logger = getLogger(__name__)


class WarmStarter:
    @deprecated('Not currently supported.')
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
            self.opt = pyomo_appsi.solvers.Gurobi()
            self.std_opt = pyo.SolverFactory('gurobi_direct')
            self.options = {'LogFile': './my_gurobi_log.log'}
        elif self.config.solver_name == 'cbc':
            self.std_opt = pyo.SolverFactory('cbc')

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
        self.iteration_limit = config.mga_inputs.get('iteration_limit', 2)
        self.time_limit_hrs = config.mga_inputs.get('time_limit_hrs', 12)
        self.cost_epsilon = config.mga_inputs.get('cost_epsilon', 0.01)

        # internal records
        self.solve_records: list[tuple[Expression, Sequence[float]]] = []
        """(solve vector, resulting axis vector)"""
        self.solve_count = 0

        logger.info(
            'Initialized WARM STARTER sequencer with MGA Axis %s and weighting %s',
            self.mga_axis.name,
            self.mga_weighting.name,
        )

    def start(self):
        """Run the sequencer"""
        # ==== basic sequence ====
        # 1. Load the model data, which may involve filtering it down if source tracing
        # 2. Instantiate a Vector Manager pull in extra data to build out data for axis
        # 3. Solve the base model using persistent solver
        # 4. Adjust the model
        # 5. Start the re-solve loop

        # 1. Load data
        hybrid_loader = HybridLoader(db_connection=self.con, config=self.config)
        data_portal: DataPortal = hybrid_loader.load_data_portal(myopic_index=None)
        instance: TemoaModel = build_instance(
            loaded_portal=data_portal, model_name=self.config.scenario, silent=self.config.silent
        )

        # 2.  Instantiate the vector manager
        vector_manager: VectorManager = get_manager(
            axis=self.mga_axis, model=instance, weighting=self.mga_weighting, con=self.con
        )

        # 3. Persistent solver setup

        # self.opt.set_instance(instance)
        tic = datetime.now()
        res: Results = self.std_opt.solve(instance, options=self.options)
        # TODO:  Experiment with this...  Not clear if it is needed to enable warm starts/persistent behavior
        toc = datetime.now()
        # load variables after first solve
        # self.std_opt.load_vars()
        elapsed = toc - tic
        self.solve_count += 1
        logger.info(f'Initial solve time: {elapsed.total_seconds():.4f}')
        # pts = np.array(
        #     [pyo.value(instance.V_FlowOut[idx]) for idx in instance.V_FlowOut.index_set()]
        # ).reshape((-1, 1))
        status = res['Solver'].termination_condition
        # status = res.termination_condition
        logger.debug('Termination condition: %s', status.name)
        # if status != pyomo_appsi.base.TerminationCondition.optimal:
        #     logger.error('Abnormal termination condition')
        #     sys.exit(-1)

        # 4. Capture cost and make it a constraint
        tot_cost = pyo.value(instance.TotalCost)
        logger.info('Completed initial solve with total cost:  %0.2f', tot_cost)
        logger.info('Relaxing cost by fraction:  %0.3f', self.cost_epsilon)
        # get hook on the expression generator for total cost...
        cost_expression = TotalCost_rule(instance)
        instance.cost_cap = pyo.Constraint(
            expr=cost_expression <= (1 + self.cost_epsilon) * tot_cost
        )
        # self.opt.add_constraints([instance.cost_cap])

        # 5. replace the objective and prep for iterative solving
        instance.del_component(instance.TotalCost)
        # self.opt.set_instance(instance)
        # self.opt.config.load_solution = False

        # 6. solve the basis vectors, if provided by manager
        basis_vectors = vector_manager.basis_vectors()
        if basis_vectors:
            for vector in basis_vectors:
                success = self.solve_instance_warmstart(instance, vector)
                if success:
                    pts = vector_manager.notify()
                    self.solve_records.append((vector, pts))
                self.process_solve_results(instance, vector)
            vector_manager.basis_runs_complete()  # notification...

        # 7. Execute re-solve loop until stopping conditions are met
        while not vector_manager.stop_resolving() and not self.internal_stop:
            print(
                f'iter {self.solve_count}:',
                f'vecs_avail: {vector_manager.input_vectors_available()}',
            )
            vector = vector_manager.next_input_vector()
            # vector = vector_manager.random_input_vector()
            if vector is None:
                logger.warning(
                    'During re-solve loop, a None vector was received.  Process terminated early.'
                )
                break
            success = self.solve_instance_warmstart(instance, vector)
            if success:
                pts = vector_manager.notify()
                self.solve_records.append((vector, pts))
            self.process_solve_results(instance, vector)

            self.solve_count += 1
            if self.solve_count >= self.iteration_limit:
                self.internal_stop = True

        # 8. Wrap it up
        vector_manager.finalize_tracker()
        pass

    def solve_instance_warmstart(self, instance: TemoaModel, vector) -> bool:
        instance.obj = pyo.Objective(expr=vector)
        # self.opt.set_objective(instance.obj)
        # instance.obj.display()
        tic = datetime.now()
        res = self.std_opt.solve(instance, warmstart=True, tee=True, options=self.options)
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
        # self.std_opt.load_vars()
        instance.del_component(instance.obj)
        return status == pyo.TerminationCondition.optimal

    def solve_instance_appsi(self, instance, vector) -> bool:
        """
        Solve the MGA instance
        :param instance: the model instance
        :param vector: the objective vector to use
        :return: True if solve was successful, False otherwise
        """
        instance.obj = pyo.Objective(expr=vector)
        self.opt.set_objective(instance.obj)
        # instance.obj.display()
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
        self.opt.load_vars()
        instance.del_component(instance.obj)
        return res.termination_condition == pyomo_appsi.base.TerminationCondition.optimal

    def process_solve_results(self, instance, vector):
        pass

    def __del__(self):
        self.con.close()
