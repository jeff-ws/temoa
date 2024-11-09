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

"""
from collections import namedtuple, defaultdict
from itertools import product
from logging import getLogger

from temoa.temoa_model.temoa_config import TemoaConfig

logger = getLogger(__name__)


class Tweak:
    """
    objects of this class represent individual tweaks to single data elements for a Monte Carlo run
    """

    def __init__(self, param_name: str, indices: tuple, adjustment: str, value: float):
        if not isinstance(indices, tuple):
            raise TypeError('indices must be a tuple')
        if adjustment not in {'r', 'a', 's'}:
            raise ValueError('adjustment must be either r/a/s')
        if not isinstance(value, float | int):
            raise TypeError('value must be a float or int')

        self.param_name = param_name
        self.indices = indices
        self.adjustment = adjustment
        self.value = value


RowData = namedtuple('RowData', ['run', 'param_name', 'indices', 'adjustment', 'value'])


class TweakFactory:
    """
    factor (likely a singleton) to manufacture Tweaks from input data
    """

    def __init__(self, data_store: dict):
        """
        make a new factor and use data_store as a validation tool
        :param data_store: the data dictionary holding the base values for the model
        """
        if not isinstance(data_store, dict):
            raise TypeError('data_store must be a dict')
        self.val_data = data_store
        tweak_dict: dict[int, list[Tweak]] = defaultdict(list)

    def make_tweaks(self, idx: int, row: str) -> tuple[int, list[Tweak]]:
        """
        make a tuple of tweaks from the row input
        :param row: run, param, index, adjustment, value
        :return: tuple of Tweaks generated from the row
        """
        rd = self._row_parser(idx, row)
        # pry the index
        p_index = rd.indices.replace('(', '').replace(')', '')  # remove any optional parens
        tokens = p_index.split('|')
        tokens = [t.strip() for t in tokens]
        tweaks = []
        # locate all 'multi' indices...
        index_vals: dict[int, list] = defaultdict(list)
        for pos, token in enumerate(tokens):
            if '/' in token:  # it is a multi-token
                sub_tokens = token.split('/')
                sub_tokens = [t.strip() for t in sub_tokens]
                for sub_token in sub_tokens:
                    try:  # integer conversion
                        sub_token = int(sub_token)
                        index_vals[pos].append(sub_token)
                    except ValueError:
                        index_vals[pos].append(sub_token)
            else:  # singleton
                try:  # integer conversion
                    token = int(token)
                    index_vals[pos].append(token)
                except ValueError:
                    index_vals[pos].append(token)

        # iterate through the positions and make all sets of indices...
        index_groups = [index_vals[pos] for pos in sorted(index_vals.keys())]
        all_inedexes = product(*index_groups)
        res = [
            Tweak(param_name=rd.param_name, indices=index, adjustment=rd.adjustment, value=rd.value)
            for index in all_inedexes
        ]
        return rd.run, res

    def _row_parser(self, idx: int, row: str) -> RowData:
        tokens = row.strip().split(',')
        tokens = [t.strip() for t in tokens]
        # convert the run number
        try:
            tokens[0] = int(tokens[0])
        except ValueError:
            raise ValueError('run number at index {idx} must be an integer')
        # convert the value
        try:
            tokens[-1] = float(tokens[-1])
        except ValueError:
            raise ValueError('value at index {idx} must be numeric')
        rd = RowData(*tokens)

        # make other checks...
        if not rd.param_name in self.val_data:
            # the param name should be a key value in the data dictionary
            raise ValueError(
                f'param_name at index: {idx} is either invalid or not represented in the input dataset'
            )
        if not rd.adjustment in {'r', 'a', 's'}:
            raise ValueError(f'adjustment at index {idx} must be either r/a/s')
        # check for no "empty" indices in the index
        if '||' in rd.indices:
            raise ValueError(
                f'indices at index {idx} cannot contain empty marker: ||.  Did you mean to put in wildcard "*"?'
            )
        return rd


class MCRun:
    """
    objects of this class represent individual run settings for Monte Carlo.

    They will hold the "data tweaks" gathered from input file for application to the base data
    """

    def __init__(self, config: TemoaConfig):
        self.config = config

    def prescreen_input_file(self):
        pass
