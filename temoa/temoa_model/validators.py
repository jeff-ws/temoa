"""
These "validators" are used as validation tools for several elements in the TemoaModel

Written by:  J. F. Hyink
jeff@westernspark.us
https://westernspark.us
Created on:  9/27/23

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
import re
from collections import defaultdict
from logging import getLogger
from typing import TYPE_CHECKING

from pyomo.environ import NonNegativeReals

if TYPE_CHECKING:
    from temoa.temoa_model.temoa_model import TemoaModel


logger = getLogger(__name__)


def validate_linked_tech(M: 'TemoaModel') -> bool:
    """
    A validation that for all the linked techs, they have the same lifetime in each possible vintage
    :param M:
    :return:
    """
    logger.debug('Starting to validate linked techs.')
    # gather the tech-linked_tech pairs
    tech_pairs = {(k[0], k[1], v) for (k, v) in M.LinkedTechs.items() if v in M.time_optimize}  # (r, t,
    # linked_tech) tuples

    # get the lifetimes by (r, t) and v for comparison
    lifetimes: dict[tuple, dict] = defaultdict(dict)
    for r, t, v in M.LifetimeProcess:
        lifetimes[r, t][v] = M.LifetimeProcess[r, t, v]
    # compare the dictionary of v: lifetime for each pair
    success = all(
        (lifetimes[r, t] == lifetimes[r, linked_tech] for (r, t, linked_tech) in tech_pairs)
    )

    if success:
        logger.debug('Successfully screened all linked techs for lifetime compatibility.')
        return True
    else:  # log the problems...
        for r, t, linked_tech in tech_pairs:
            # compare vintages (should be same)
            tech_vintages = lifetimes.get((r, t))
            # make sure they have vintages in LifetimeProcess
            if not tech_vintages:
                logger.error(
                    'Tech %s in region %s has no valid vintages in LifetimeProcess',
                    t,
                    r,
                )
            linked_tech_vintages = lifetimes.get((r, linked_tech))
            if not linked_tech_vintages:
                logger.error(
                    'Linked tech %s in region %s has no valid vintages in LifetimeProcess',
                    t,
                    r,
                )

            # make sure they have the SAME eligible vintages
            if tech_vintages and linked_tech_vintages:
                vintage_disparities = lifetimes[r, t].keys() ^ lifetimes[r, linked_tech].keys()
                if vintage_disparities:
                    logger.error(
                        'Tech %s and %s are linked but have differing baseline vintages:\n  %s',
                        t,
                        linked_tech,
                        vintage_disparities,
                    )

                # check for same lifetimes, using the base tech as a baseline
                vintage_lifetimes = lifetimes[r, t]
                for v in vintage_lifetimes.keys():
                    # get the corresponding lifetime for the linked tech
                    linked_vintage_lifetime = lifetimes.get((r, linked_tech)).get(v)
                    if vintage_lifetimes[v] != linked_vintage_lifetime:
                        logger.error(
                            'Techs %s and %s do not have the same lifetime in vintage %s',
                            t,
                            linked_tech,
                            v,
                        )
        logger.error('Temoa Exiting...')
        return False


def region_check(M: 'TemoaModel', region) -> bool:
    """
    Validate the region name (letters + numbers only + underscore)
    """
    # screen against illegal names
    illegal_region_names = {
        'global',
    }
    if region in illegal_region_names:
        return False

    # if this matches, return is true, fail -> false
    if re.match(r'[a-zA-Z0-9_]+\Z', region):  # string that has only letters and numbers
        return True
    return False


def linked_region_check(M: 'TemoaModel', region_pair) -> bool:
    """
    Validate a pair of regions (r-r format where r ∈ M.R )
    """
    linked_regions = re.match(r'([a-zA-Z0-9_]+)\-([a-zA-Z0-9_]+)\Z', region_pair)
    if linked_regions:
        r1 = linked_regions.group(1)
        r2 = linked_regions.group(2)
        if (
            all(r in M.regions for r in (r1, r2)) and r1 != r2
        ):  # both captured regions are in the set of M.R
            return True
    return False


def region_group_check(M: 'TemoaModel', rg) -> bool:
    """
    Validate the region-group name (region or regions separated by '+')
    """
    if '-' in rg:  # it should just be evaluated as a linked_region
        return linked_region_check(M, rg)
    if re.search(r'\A[a-zA-Z0-9\+_]+\Z', rg):
        # it has legal characters only
        if '+' in rg:
            # break up the group
            contained_regions = rg.strip().split('+')
            if all(t in M.regions for t in contained_regions) and len(
                set(contained_regions)
            ) == len(contained_regions):  # no dupes
                return True
        else:  # it is a singleton
            return (rg in M.regions) or rg == 'global'
    return False


def tech_groups_set_check(M: 'TemoaModel', rg, g, t) -> bool:
    """
    Validate this entry to the tech_groups set
    :param M: the model
    :param rg: region-group index
    :param g: tech group name
    :param t: tech
    :return: True if valid entry, else False
    """
    return all((region_group_check(M, rg), g in M.groups, t in M.tech_all))


# TODO:  Several of these param checkers below are not in use because the params cannot
# accept new values for the indexing sets that aren't in a recognized set.  Now that we are
# making the GlobalRegionalIndices, we can probably come back and employ them instead of using
# the buildAction approach


def activity_param_check(M: 'TemoaModel', val, rg, p, t) -> bool:
    """
    Validate the index and the value for an entry into an activity param indexed with region-groups
    :param M: the model
    :param val: the value of the parameter for this index
    :param rg: region-group
    :param p: time period
    :param t: tech
    :return: True if all OK
    """
    return all(
        (
            val in NonNegativeReals,  # the value should be in this set
            region_group_check(M, rg),
            p in M.time_optimize,
            t in M.tech_all,
        )
    )


def capacity_param_check(M: 'TemoaModel', val, rg, p, t, carrier) -> bool:
    """
    validate entries to capacity params
    :param M: the model
    :param val: the param value at this index
    :param rg: region-group
    :param p: time period
    :param t: tech
    :param carrier: commodity carrier
    :return: True if all OK
    """
    return all(
        (
            val in NonNegativeReals,
            region_group_check(M, rg),
            p in M.time_optimize,
            t in M.tech_all,
            carrier in M.commodity_carrier,
        )
    )


def activity_group_param_check(M: 'TemoaModel', val, rg, p, g) -> bool:
    """
    validate entries into capacity groups
    :param M: the model
    :param val: the value at this index
    :param rg: region-group
    :param p: time period
    :param g: tech group name
    :return: True if all OK
    """
    return all(
        (val in NonNegativeReals, region_group_check(M, rg), p in M.time_optimize, g in M.groups)
    )


def emission_limit_param_check(M: 'TemoaModel', val, rg, p, e) -> bool:
    """
    validate entries into EmissionLimit param
    :param M: the model
    :param val: the value at this index
    :param rg: region-group
    :param p: time period
    :param e: commodity emission
    :return: True if all OK
    """
    return all((region_group_check(M, rg), p in M.time_optimize, e in M.commodity_emissions))


def validate_CapacityFactorProcess(M: 'TemoaModel', val, r, s, d, t, v) -> bool:
    """
    validate the rsdtv index
    :param val: the parameter value
    :param M: the model
    :param r: region
    :param s: season
    :param d: time of day
    :param t: tech
    :param v: vintage
    :return:
    """
    return all(
        (
            r in M.regions,
            s in M.time_season,
            d in M.time_of_day,
            t in M.tech_all,
            v in M.vintage_all,
            0 <= val <= 1.0,
        )
    )

def validate_Efficiency(M: 'TemoaModel', val, r, si, t, v, so) -> bool:
    """Handy for troubleshooting problematic entries"""

    if all(
        (
            isinstance(val, float),
            val > 0,
            r in M.RegionalIndices,
            si in M.commodity_physical,
            t in M.tech_all,
            so in M.commodity_carrier,
            v in M.vintage_all,
        )
    ):
        return True
    print ('r', r in M.RegionalIndices)
    print( 'si', si in M.commodity_physical )
    print( 't', t in M.tech_all)
    print( 'v', v in M.vintage_all)
    print( 'so', so in M.commodity_carrier )
    return False
