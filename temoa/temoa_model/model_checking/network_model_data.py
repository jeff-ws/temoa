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
Created on:  3/10/24

"""
import logging
import sqlite3
from collections import namedtuple, defaultdict
from itertools import chain

from pyomo.core import ConcreteModel

from temoa.temoa_model.temoa_model import TemoaModel

Tech = namedtuple('Tech', ['region', 'period', 'ic', 'tech_name', 'vintage', 'oc'])
Linked_Tech = namedtuple('Linked_Tech', ['region', 'driver', 'emission', 'driven'])

logger = logging.getLogger(__name__)


class NetworkModelData:
    """A simple encapsulation of data needed for the Commodity Network"""

    def __init__(self, **kwargs):
        self.demand_commodities: dict[tuple[str, int | str], set[str]] = kwargs.get(
            'demand_commodities'
        )
        self.source_commodities: set[str] = kwargs.get('source_commodities')
        self.all_commodities: set[str] = kwargs.get('all_commodities')
        self.available_techs: dict[tuple[str, int | str], set[Tech]] = kwargs.get('available_techs')
        self.available_linked_techs: set[Linked_Tech] = kwargs.get('available_linked_techs', set())

    def __str__(self):
        return (
            f'all commodities: {len(self.all_commodities)}, demand commodities: {len(self.demand_commodities)}, '
            f'source commodities: {len(self.source_commodities)},'
            f'available techs: {len(tuple(chain(*self.available_techs.values())))}, '
            f'linked techs: {len(self.available_linked_techs)}'
        )


def build(data) -> NetworkModelData:
    builder = _get_builder(data)
    return builder(data)


def _get_builder(data):
    if isinstance(data, TemoaModel | ConcreteModel):
        # dev note:  The built instance will be a ConcreteModel
        builder = _build_from_model
        return builder
    elif isinstance(data, sqlite3.Connection):
        builder = _build_from_db
        return builder
    else:
        raise NotImplementedError('cannot build from that type of data')


def _build_from_model(M: TemoaModel) -> NetworkModelData:
    """Build a NetworkModelData from a TemoaModel"""
    res = NetworkModelData()
    res.all_commodities = set(M.commodity_all)
    res.source_commodities = set(M.commodity_source)
    dem_com = defaultdict(set)
    for r, p, d in M.Demand:
        dem_com[r, p].add(d)
    res.demand_commodities = dem_com
    techs = defaultdict(set)
    # scan non-annual techs...
    for r, p, s, d, ic, tech, v, oc in M.activeFlow_rpsditvo:
        techs[r, p].add(Tech(r, p, ic, tech, v, oc))
    # scan annual techs...
    for r, p, ic, tech, v, oc in M.activeFlow_rpitvo:
        techs[r, p].add(Tech(r, p, ic, tech, v, oc))
    res.available_techs = techs
    linked_techs = set()
    for r, driver, emission, driven in M.LinkedTechs:
        linked_techs.add(Linked_Tech(r, driver, emission, driven))
    res.available_linked_techs = linked_techs
    logger.debug('built network data: %s', res.__str__())
    return res


def _build_from_db(con: sqlite3.Connection) -> NetworkModelData:
    """Build NetworkModelData object from a sqlite database."""
    # dev note:  sadly, this will duplicate some code, I think.  Perhaps a later refactoring can
    #            re-use some of the hybrid loader code in a clear way.  Not too much overlap, though
    res = NetworkModelData()
    cur = con.cursor()
    raw = cur.execute('SELECT commodities.comm_name FROM commodities').fetchall()
    res.all_commodities = {t[0] for t in raw}
    raw = cur.execute("SELECT commodities.comm_name FROM commodities WHERE flag = 's'").fetchall()
    res.source_commodities = {t[0] for t in raw}
    # use Demand to get the region, period specific demand comms
    raw = cur.execute('SELECT regions, periods, demand_comm FROM main.Demand').fetchall()
    demand_dict = defaultdict(set)
    for r, p, d in raw:
        demand_dict[r, p].add(d)
    res.demand_commodities = demand_dict
    # need lifetime to screen techs... :/
    default_lifetime = TemoaModel.default_lifetime_tech
    query = (
        '  SELECT main.Efficiency.regions, input_comm, Efficiency.tech, Efficiency.vintage, output_comm,  '
        f'  coalesce(main.LifetimeProcess.life_process, main.LifetimeTech.life, {default_lifetime}) AS lifetime '
        '   FROM main.Efficiency '
        '    LEFT JOIN main.LifetimeProcess '
        '       ON main.Efficiency.tech = LifetimeProcess.tech '
        '       AND main.Efficiency.vintage = LifetimeProcess.vintage '
        '       AND main.Efficiency.regions = LifetimeProcess.regions '
        '    LEFT JOIN main.LifetimeTech '
        '       ON main.Efficiency.tech = main.LifetimeTech.tech '
        '     AND main.Efficiency.regions = main.LifeTimeTech.regions '
        '   JOIN time_periods '
        '   ON Efficiency.vintage = time_periods.t_periods '
    )
    raw = cur.execute(query).fetchall()
    periods = cur.execute('SELECT t_periods FROM time_periods').fetchall()
    periods = {t[0] for t in periods}
    techs = defaultdict(set)
    for element in raw:
        for p in periods:
            (r, ic, tech, v, oc, lifetime) = element
            if v <= p < v + lifetime:
                techs[r, p].add(Tech(r, p, ic, tech, v, oc))
    res.available_techs = techs

    # pick up the linked techs...
    raw = cur.execute(
        'SELECT primary_region, primary_tech, emis_comm, linked_tech from main.LinkedTechs'
    ).fetchall()
    res.available_linked_techs = {
        Linked_Tech(region=r, driver=driver, emission=emiss, driven=driven)
        for (r, driver, emiss, driven) in raw
    }

    res.available_linked_techs = []
    logger.debug('built network data: %s', res.__str__())
    return res
