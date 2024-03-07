"""
Basic-level atomic functions that can be used by a sequencer, as needed

Written by:  J. F. Hyink
jeff@westernspark.us
https://westernspark.us
Created on:  11/15/23

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

from logging import getLogger
from pathlib import Path
from sys import stderr as SE
from time import time
from typing import Tuple

import pyomo.opt
from pyomo.environ import DataPortal, Suffix, Var, Constraint, value, UnknownSolver, SolverFactory
from pyomo.opt import SolverResults, SolverStatus, TerminationCondition

from temoa.temoa_model.pformat_results import pformat_results
from temoa.temoa_model.temoa_config import TemoaConfig
from temoa.temoa_model.temoa_model import TemoaModel

logger = getLogger(__name__)


def load_portal_from_dat(dat_file: Path, silent: bool = False) -> DataPortal:
    loaded_portal = DataPortal(model=TemoaModel())

    if dat_file.suffix != '.dat':
        logger.error('Attempted to load data from file %s which is not a .dat file', dat_file)
        raise TypeError('file loading error occurred, see log')
    hack = time()
    if not silent:
        SE.write('[        ] Reading data files.')
        SE.flush()

    logger.debug('Started loading the DataPortal from the .dat file: %s', dat_file)
    loaded_portal.load(filename=str(dat_file))

    if not silent:
        SE.write('\r[%8.2f] Data read.\n' % (time() - hack))
    logger.debug('Finished creating the DataPortal from the .dat')
    return loaded_portal


def build_instance(
    loaded_portal: DataPortal,
    model_name=None,
    silent=False,
    keep_lp_file=False,
    lp_path: Path = None,
) -> TemoaModel:
    """
    Build a Temoa Instance from data
    :param loaded_portal: a DataPortal instance
    :param silent: Run silently
    :param model_name: Optional name for this instance
    :return: a built TemoaModel
    """
    model = TemoaModel()

    model.dual = Suffix(direction=Suffix.IMPORT)
    # self.model.rc = Suffix(direction=Suffix.IMPORT)
    # self.model.slack = Suffix(direction=Suffix.IMPORT)

    hack = time()
    if not silent:
        SE.write('[        ] Creating model instance.')
        SE.flush()
    logger.info('Started creating model instance from data')
    instance = model.create_instance(loaded_portal, name=model_name)
    if not silent:
        SE.write('\r[%8.2f] Instance created.\n' % (time() - hack))
        SE.flush()
    logger.info('Finished creating model instance from data')

    # save LP if requested
    if keep_lp_file:
        if not lp_path:
            logger.warning('Requested "keep LP file", but no path is provided...skipped')
        else:
            if not Path.is_dir(lp_path):
                Path.mkdir(lp_path)
            filename = lp_path / 'model.lp'
            instance.write(filename, format='lp', io_options={'symbolic_solver_labels': True})

    # gather some stats...
    c_count = 0
    v_count = 0
    for constraint in instance.component_objects(ctype=Constraint):
        c_count += len(constraint)
    for var in instance.component_objects(ctype=Var):
        v_count += len(var)
    logger.info('model built...  Variables: %d, Constraints: %d', v_count, c_count)
    return instance


def solve_instance(
    instance: TemoaModel, solver_name, silent: bool = False
) -> Tuple[TemoaModel, SolverResults]:
    """
    Solve the instance and return a loaded instance
    :param silent: Run silently
    :param solver_name: The name of the solver to request from the SolverFactory
    :param instance: the instance to solve
    :return: loaded instance
    """
    # TODO:  Type the solver in signature

    # QA the solver name and get a handle on solver
    if not solver_name:
        logger.error('No solver specified in solve sequence')
        raise TypeError('Error occurred during solve, see log')
    optimizer = SolverFactory(solver_name)
    if isinstance(optimizer, UnknownSolver):
        logger.error(
            'Failed to create a solver instance for name: %s.  Check name and availability on '
            'this system',
            solver_name,
        )
        raise TypeError('Failed to make Solver instance.  See log.')

    hack = time()
    if not silent:
        SE.write('[        ] Solving.')
        SE.flush()

    try:
        logger.info(
            'Starting the solve process using %s solver on model %s', solver_name, instance.name
        )
        if solver_name == 'neos':
            raise NotImplementedError('Neos based solve is not currently supported')
            # result = options.optimizer.solve(instance, opt=options.solver)
        else:
            if solver_name == 'cbc':
                pass
                # dev note:  I think these options are outdated.  Getting decent results without them...
                #            preserved for now.
                # Solver options. Reference:
                # https://genxproject.github.io/GenX/dev/solver_configuration/
                # optimizer.options["dualTolerance"] = 1e-6
                # optimizer.options["primalTolerance"] = 1e-6
                # optimizer.options["zeroTolerance"] = 1e-12
                # optimizer.options["crossover"] = 'off'

            elif solver_name == 'cplex':
                # Note: these parameter values are taken to be the same as those in PyPSA
                # (see: https://pypsa-eur.readthedocs.io/en/latest/configuration.html)
                optimizer.options['lpmethod'] = 4  # barrier
                optimizer.options['solutiontype'] = 2  # non basic solution, ie no crossover
                optimizer.options['barrier convergetol'] = 1.0e-5
                optimizer.options['feasopt tolerance'] = 1.0e-6

            elif solver_name == 'highs':
                optimizer = SolverFactory('appsi_highs')

            # TODO: still need to add gurobi parameters?

            result = optimizer.solve(
                instance, load_solutions=False
            )  # , tee=True)  <-- if needed for T/S
            if (
                result.solver.status == SolverStatus.ok
                and result.solver.termination_condition == TerminationCondition.optimal
            ):
                instance.solutions.load_from(result)

            # opt = appsi.solvers.Highs()
            # # opt.config.load_solution=False
            # try:
            #     res = opt.solve(instance)
            #     result = res.termination_condition.name
            # except RuntimeError as e:
            #     print('failed highs solve')
            #     result = None

            logger.info('Solve process complete')
            logger.debug('Solver results: \n %s', result)

        if not silent:
            SE.write('\r[%8.2f] Model solved.\n' % (time() - hack))
            SE.flush()

    except Exception as model_exc:
        # yield "Exception found in solve_temoa_instance\n"
        SE.write('Exception found in solve_temoa_instance\n')
        # yield str(model_exc) + '\n'
        SE.write(str(model_exc))
        raise model_exc

    # TODO:  It isn't clear that we need to push the solution values into the Result object:  it appears to be used in
    #        pformat results, but why not just use the instance?
    instance.solutions.store_to(result)
    return instance, result


def check_solve_status(result: SolverResults) -> tuple[bool, str]:
    """
    Check the status of the solve.
    :param result: the results object returned by the solver
    :return: tuple of status boolean (True='optimal', others False), and string message if not optimal
    """
    # dev note:  pyomo now offerst the check function below, which simplifies this function
    #            probably to a 1-liner.  Unsure if it is supported for all solvers, so will leave this
    #            for now.

    soln = result['Solution']
    # solv = result['Solver']  # currently unused, but may want it later
    # prob = result['Problem']  # currently unused, but may want it later

    lesser_responses = ('feasible', 'globallyOptimal', 'locallyOptimal')
    logger.info('The solver reported status as: %s', soln.Status)
    if pyomo.opt.check_optimal_termination(results=result):
        return True, ''
    else:
        return False, f'{soln.Status} was returned from solve'


def handle_results(instance: TemoaModel, results, options: TemoaConfig):
    hack = time()
    if not options.silent:
        msg = '[        ] Calculating reporting variables and formatting results.'
        # yield 'Calculating reporting variables and formatting results.'
        SE.write(msg)
        SE.flush()

    output_stream = pformat_results(instance, results, options)

    if not options.silent:
        SE.write('\r[%8.2f] Results processed.\n' % (time() - hack))
        SE.flush()

    if options.stream_output:
        print(output_stream.getvalue())
    # normal (non-MGA) run will have a TotalCost as the OBJ:
    if hasattr(instance, 'TotalCost'):
        logger.info('TotalCost value: %0.2f', value(instance.TotalCost))
    # MGA runs should have either a FirstObj or SecondObj
    if hasattr(instance, 'FirstObj'):
        logger.info('MGA First Obj value: %0.2f', value(instance.FirstObj))
    elif hasattr(instance, 'SecondObj'):
        logger.info('MGA Second Obj value: %0.2f', value(instance.SecondObj))
    return
