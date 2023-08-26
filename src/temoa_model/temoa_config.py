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
"""
import os
from os.path import abspath, isfile, splitext

from definitions import PROJECT_ROOT
from src.temoa_model.dat_file_maker import db_2_dat

from logging import getLogger

logger = getLogger(__name__)

class TemoaConfig( object ):
	states = (
	('mga', 'exclusive'),
	)

	tokens = (
		'dot_dat',
		'output',
		'scenario',
		'how_to_cite',
		'version',
		'solver',
		'neos',
		'keep_pyomo_lp_file',
		'saveEXCEL',
		'myopic'
		'myopic_periods'
		'keep_myopic_databases'
		'saveDUALS'
		'saveTEXTFILE',
		'mgaslack',
		'mgaiter',
		'path_to_data',
		'path_to_logs',
		'mgaweight'
	)

	t_ANY_ignore  = '[ \t]'

	def __init__(self, **kwargs):
		# Make compatible with Python 2.7 and 3
		try:
			import queue
		except:
			import Queue as queue

		self.__error          = list()
		self.__mga_todo       = queue.Queue()
		self.__mga_done       = queue.Queue()

		self.file_location    = None
		self.dot_dat          = list() # Use Kevin's name.
		self.output           = None # May update to a list if multiple output is required.
		self.scenario         = None
		self.saveEXCEL        = False
		self.myopic           = False
		self.myopic_periods     = 0
		self.KeepMyopicDBs    = False
		self.saveDUALS     	  = False
		self.saveTEXTFILE     = False
		self.how_to_cite      = None
		self.version          = False
		self.neos             = False
		self.generateSolverLP = False
		self.keepPyomoLP      = False
		self.mga              = None # mga slack value
		self.mga_iter         = None
		self.mga_weight       = None

		# To keep consistent with Kevin's argumetn parser, will be removed in the future.
		self.graph_format     = None
		self.show_capacity    = False
		self.graph_type       = 'separate_vintages'
		self.use_splines      = False

		#Introduced during UI Development
		self.path_to_data    = os.path.join(PROJECT_ROOT, 'data_files') #re.sub('temoa_model$', 'data_files', dirname(abspath(__file__)))# Path to where automated excel and text log folder will be save as output.
		self.path_to_logs     = os.path.join(PROJECT_ROOT, 'output_files', 'debug_logs') #self.path_to_data+sep+"debug_logs" #Path to where debug logs will be generated for each run. By default in debug_logs folder in db_io.
		self.path_to_lp_files = None
		self.abort_temoa	  = False

		if 'd_solver' in kwargs.keys():
			self.solver = kwargs['d_solver']
		else:
			self.solver = None

		logger.debug("Created an empty TemoaConfig instance")


	def __repr__(self):
		width = 25
		spacer = '\n' + '-'*width + '\n'
		msg = spacer
		msg += '{:>{}s}: {}\n'.format('Config file', width, self.file_location)
		for i in self.dot_dat:
			if self.dot_dat.index(i) == 0:
				msg += '{:>{}s}: {}\n'.format('Input file', width, i)
			else:
				msg += '{:>25s}  {}\n'.format(' ', i)
		msg += '{:>{}s}: {}\n'.format('Output file', width, self.output)
		msg += '{:>{}s}: {}\n'.format('Scenario', width, self.scenario)
		msg += '{:>{}s}: {}\n'.format('Spreadsheet output', width, self.saveEXCEL)
		msg += '{:>{}s}: {}\n'.format('Myopic scheme', width, self.myopic)
		msg += '{:>{}s}: {}\n'.format('Myopic years', width, self.myopic_periods)
		msg += '{:>{}s}: {}\n'.format('Retain myopic databases', width, self.KeepMyopicDBs)
		msg += spacer
		msg += '{:>{}s}: {}\n'.format('Citation output status', width, self.how_to_cite)
		msg += '{:>{}s}: {}\n'.format('NEOS status', width, self.neos)
		msg += '{:>{}s}: {}\n'.format('Version output status', width, self.version)
		msg += spacer
		msg += '{:>{}s}: {}\n'.format('Selected solver status', width, self.solver)
		msg += '{:>{}s}: {}\n'.format('Solver LP write status', width, self.generateSolverLP)
		msg += '{:>{}s}: {}\n'.format('Pyomo LP write status', width, self.keepPyomoLP)
		msg += spacer
		msg += '{:>{}s}: {}\n'.format('MGA slack value', width, self.mga)
		msg += '{:>{}s}: {}\n'.format('MGA # of iterations', width, self.mga_iter)
		msg += '{:>{}s}: {}\n'.format('MGA weighting method', width, self.mga_weight)
		msg += '**NOTE: If you are performing MGA runs, navigate to the DAT file and make any modifications to the MGA sets before proceeding.'
		return msg

	def t_ANY_COMMENT(self, t):
		r'\#.*'
		pass

	def t_dot_dat(self, t):
		r'--input[\s\=]+[-\\\/\:\.\~\w]+(\.dat|\.db|\.sqlite)\b'
		self.dot_dat.append(abspath(t.value.replace('=', ' ').split()[1]))

	def t_output(self, t):
		r'--output[\s\=]+[-\\\/\:\.\~\w]+(\.db|\.sqlite)\b'
		self.output = abspath(t.value.replace('=', ' ').split()[1])

	def t_scenario(self, t):
		r'--scenario[\s\=]+\w+\b'
		self.scenario = t.value.replace('=', ' ').split()[1]

	def t_saveEXCEL(self, t):
		r'--saveEXCEL\b'
		self.saveEXCEL = True

	def t_saveDUALS(self, t):
		r'--saveDUALS\b'
		self.saveDUALS = True

	def t_myopic(self, t):
		r'--myopic\b'
		self.myopic = True

	def t_myopic_periods(self, t):
		r'--myopic_periods[\s\=]+[\d]+'
		self.myopic_periods = int(t.value.replace('=', ' ').split()[1])

	def t_keep_myopic_databases(self, t):
		r'--keep_myopic_databases\b'
		self.KeepMyopicDBs = True

	def t_saveTEXTFILE(self, t):
		r'--saveTEXTFILE\b'
		self.saveTEXTFILE = True

	def t_path_to_data(self, t):
		r'--path_to_data[\s\=]+[-\\\/\:\.\~\w\ ]+\b'
		self.path_to_data = abspath(t.value.replace('=', ',').split(",")[1])

	def t_path_to_logs(self, t):
		r'--path_to_logs[\s\=]+[-\\\/\:\.\~\w\ ]+\b'
		self.path_to_logs = abspath(t.value.replace('=', ',').split(",")[1])

	def t_how_to_cite(self, t):
		r'--how_to_cite\b'
		self.how_to_cite = True

	def t_version(self, t):
		r'--version\b'
		self.version = True

	def t_neos(self, t):
		r'--neos\b'
		self.neos = True

	def t_solver(self, t):
		r'--solver[\s\=]+\w+\b'
		self.solver = t.value.replace('=', ' ').split()[1]

	def t_keep_pyomo_lp_file(self, t):
		r'--keep_pyomo_lp_file\b'
		self.keepPyomoLP = True

	def t_begin_mga(self, t):
		r'--mga[\s\=]+\{'
		t.lexer.push_state('mga')
		t.lexer.level = 1

	def t_mga_mgaslack(self, t):
		r'slack[\s\=]+[\.\d]+'
		self.mga = float(t.value.replace('=', ' ').split()[1])

	def t_mga_mgaiter(self, t):
		r'iteration[\s\=]+[\d]+'
		self.mga_iter = int(t.value.replace('=', ' ').split()[1])

	def t_mga_mgaweight(self, t):
		r'weight[\s\=]+(integer|normalized|distance)\b'
		self.mga_weight = t.value.replace('=', ' ').split()[1]

	def t_mga_end(self, t):
		r'\}'
		t.lexer.pop_state()
		t.lexer.level -= 1

	def t_ANY_newline(self,t):
		r'\n+|(\r\n)+|\r+' # '\n' (In linux) = '\r\n' (In Windows) = '\r' (In Mac OS)
		t.lexer.lineno += len(t.value)

	def t_ANY_error(self, t):
		if not self.__error:
			self.__error.append({'line': [t.lineno, t.lineno], 'index': [t.lexpos, t.lexpos], 'value': t.value[0]})
		elif t.lexpos - self.__error[-1]['index'][-1] == 1:
			self.__error[-1]['line' ][-1] = t.lineno
			self.__error[-1]['index'][-1] = t.lexpos
			self.__error[-1]['value'] += t.value[0]
		else:
			self.__error.append({'line': [t.lineno, t.lineno], 'index': [t.lexpos, t.lexpos], 'value': t.value[0]})
		t.lexer.skip(1)

	def next_mga(self):
		if not self.__mga_todo.empty():
			self.__mga_done.put(self.scenario)
			self.scenario = self.__mga_todo.get()
			return True
		else:
			return False

	def build(self,**kwargs):
		import ply.lex as lex, os, sys

		db_or_dat = True # True means input file is a db file. False means input is a dat file.

		if 'config' in kwargs:
			if isfile(kwargs['config']):
				self.file_location= abspath(kwargs.pop('config'))
			else:
				msg = 'No such file exists: {}'.format(kwargs.pop('config'))
				raise Exception( msg )

		self.lexer = lex.lex(module=self, **kwargs)
		if self.file_location:
			try:
				with open(self.file_location, encoding="utf8") as f:
					self.lexer.input(f.read())
			except:
				with open(self.file_location, 'r') as f:
					self.lexer.input(f.read())
			while True:
				tok = self.lexer.token()
				if not tok: break

		if self.__error:
			width = 25
			msg = '\nIllegal character(s) in config file:\n'
			msg += '-'*width + '\n'
			for e in self.__error:
				msg += "Line {} to {}: '{}'\n".format(e['line'][0], e['line'][1], e['value'])
			msg += '-'*width + '\n'
			sys.stderr.write(msg)

			try:
				txt_file = open(self.path_to_logs+os.sep+"Complete_OutputLog.log", "w")
			except BaseException as io_exc:
				sys.stderr.write("Log file cannot be opened. Please check path. Trying to find:\n"+self.path_to_logs+" folder\n")
				txt_file = open("OutputLog.log", "w")

			txt_file.write( msg )
			txt_file.close()
			self.abort_temoa = True


		if not self.dot_dat:
			raise Exception('Input file not specified.')

		for i in self.dot_dat:
			if not isfile(i):
				raise Exception('Cannot locate input file: {}'.format(i))
			i_name, i_ext = splitext(i)
			if (i_ext == '.dat') or (i_ext == '.txt'):
				db_or_dat = False
			elif (i_ext == '.db') or (i_ext == '.sqlite') or (i_ext == '.sqlite3') or (i_ext == 'sqlitedb'):
				db_or_dat = True

		if not self.output and db_or_dat:
			raise Exception('Output file not specified.')

		if db_or_dat and not isfile(self.output):
			raise Exception('Cannot locate output file: {}.'.format(self.output))

		if not self.scenario and db_or_dat:
			raise Exception('Scenario name not specified.')

		if self.mga_iter:
			for i in range(self.mga_iter):
				self.__mga_todo.put(self.scenario + '_mga_' + str(i))

		f = open(os.devnull, 'w');
		sys.stdout = f # Suppress the original DB_to_DAT.py output

		counter = 0

		for ifile in self.dot_dat:
			i_name, i_ext = splitext(ifile)
			if i_ext != '.dat':
				ofile = i_name + '.dat'
				db_2_dat(ifile, ofile, self)
				self.dot_dat[self.dot_dat.index(ifile)] = ofile
				counter += 1
		f.close()
		sys.stdout = sys.__stdout__
		if counter > 0:
			sys.stderr.write("\n{} .db DD file(s) converted\n".format(counter))