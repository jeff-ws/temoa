"""
Utility to convert sqlite database file to a pyomo-friendly .dat file.

The original contents below were originally located in the temoa_config file
"""
import re
# Adapted from DB_to_DAT.py
import sqlite3
from logging import getLogger

from temoa.temoa_model.temoa_config import TemoaConfig
from temoa.temoa_model.temoa_mode import TemoaMode

logger = getLogger(__name__)

# the tables below are ones in which we might find regional groups which should be captured
# to make the members of the RegionalGlobalIndices Set in the model.  They need to aggregated
tables_with_regional_groups = {'MaxActivity': 'regions',
                               'MinActivity': 'regions',
                               'MinAnnualCapacityFactor': 'regions',
                               'MaxAnnualCapacityFactor': 'regions',
                               'EmissionLimit': 'regions',
                               'MinActivityGroup': 'regions',
                               'MaxActivityGroup': 'regions',
                               'MinCapacityGroup': 'regions',
                               'MaxCapacityGroup': 'regions',
                               }
# TODO:  Sort out the schema for tech_groups.  RN, US_9R stuff does not comply w/ schema for this table
def db_2_dat(ifile, ofile, options: TemoaConfig):

    logger.info('Converting %s database file to .dat format', ifile)

    def construct_RegionalGlobalIndices(tables_in_db, f) -> None:
        """
        go through all tables that may include regional groups that exist within this db and:
        select the region/regions column based on table info, union the results together,
        write the set to the .dat file with appropriate name
        :param tables_in_db: the tables that exist in the db
        :param f: the output stream to write to
        :return:
        """
        tables_to_parse = set(tables_in_db) & tables_with_regional_groups.keys()
        # make the query
        query = ' UNION '.join(('SELECT ' + tables_with_regional_groups[table] + ' FROM ' + table for table in tables_to_parse))
        cur.execute(query)
        count = 0
        f.write('set RegionalGlobalIndices :=\n')
        sorted_entries = sorted(cur)  # sorting to guarantee consistent ordering going into model
        for row in sorted_entries:
            f.write(row[0])
            f.write('\n')
            count += 1
        f.write(';\n\n')
        logger.debug('Located total of %d entries for RegionalGlobalIndices', count)

    def write_tech_mga(f):
        cur.execute("SELECT tech FROM Technology")
        f.write("set tech_mga :=\n")
        for row in cur:
            f.write(row[0] + '\n')
        f.write(';\n\n')

    def write_tech_sector(f):
        sectors = set()
        cur.execute("SELECT sector FROM Technology")
        for row in cur:
            sectors.add(row[0])
        for s in sectors:
            cur.execute("SELECT tech FROM Technology WHERE sector == '" + s + "'")
            f.write("set tech_" + s + " :=\n")
            for row in cur:
                f.write(row[0] + '\n')
            f.write(';\n\n')

    def query_table(t_properties, f):
        t_type = t_properties[0]  # table type (set or param)
        t_name = t_properties[1]  # table name
        t_dtname = t_properties[2]  # DAT table name when DB table must be subdivided
        t_flag = t_properties[3]  # table flag, if any
        t_index = t_properties[4]  # table column index after which '#' should be specified
        if type(t_flag) is list:  # tech production table has a list for flags; this is currently hard-wired
            db_query = "SELECT * FROM " + t_name + " WHERE flag=='p' OR flag=='pb' OR flag=='ps'"
            cur.execute(db_query)
            if cur.fetchone() is None:
                return
            if t_type == "set":
                f.write("set " + t_dtname + " := \n")
            else:
                f.write("param " + t_dtname + " := \n")
        elif t_flag != '':  # check to see if flag is empty, if not use it to make table
            db_query = "SELECT * FROM " + t_name + " WHERE flag=='" + t_flag + "'"
            cur.execute(db_query)
            if cur.fetchone() is None:
                return
            if t_type == "set":
                f.write("set " + t_dtname + " := \n")
            else:
                f.write("param " + t_dtname + " := \n")
        else:  # Only other possible case is empty flag, then 1-to-1 correspodence between DB and DAT table names
            db_query = "SELECT * FROM " + t_name
            cur.execute(db_query)
            if cur.fetchone() is None:
                return
            if t_type == "set":
                f.write("set " + t_name + " := \n")
            else:
                f.write("param " + t_name + " := \n")
        cur.execute(db_query)
        if t_index == 0:  # make sure that units and descriptions are commented out in DAT file
            for line in cur:
                str_row = str(line[0]) + "\n"
                f.write(str_row)
        else:
            for line in cur:
                before_comments = line[:t_index + 1]
                before_comments = re.sub('[(]', '', str(before_comments))
                before_comments = re.sub('[\',)]', '    ', str(before_comments))
                after_comments = line[t_index + 2:]
                after_comments = re.sub('[(]', '', str(after_comments))
                after_comments = re.sub('[\',)]', '    ', str(after_comments))
                search_afcom = re.search(r'^\W+$', str(after_comments))  # Search if after_comments is empty.
                if not search_afcom:
                    str_row = before_comments + "# " + after_comments + "\n"
                else:
                    str_row = before_comments + "\n"
                f.write(str_row)
        f.write(';\n\n')

    #[set or param, table_name, DAT fieldname, flag (if any), index (where to insert '#')
    table_list = [
        ['set',  'time_periods',              'time_exist',          'e',            0],
        ['set',  'time_periods',              'time_future',         'f',            0],
        ['set',  'time_season',               '',                    '',             0],
        ['set',  'time_of_day',               '',                    '',             0],
        ['set',  'regions',        	          '',                    '',             0],
        ['set',  'tech_curtailment',          '',                    '',             0],
        ['set',  'tech_flex',          		  '',                    '',             0],
        ['set',  'tech_rps',          		  '',                    '',             1],
        ['set',  'tech_reserve',              '',                    '',             0],
        ['set',  'technologies',              'tech_resource',       'r',            0],
        ['set',  'technologies',              'tech_production',    ['p','pb','ps'], 0],
        ['set',  'technologies',              'tech_baseload',       'pb',           0],
        ['set',  'technologies',              'tech_storage',  		 'ps',           0],
        ['set',  'tech_ramping',              '',                    '',             0],
        ['set',  'tech_exchange',             '',                    '',             0],
        ['set',  'commodities',               'commodity_physical',  'p',            0],
        ['set',  'commodities',               'commodity_emissions', 'e',            0],
        ['set',  'commodities',               'commodity_demand',    'd',            0],
        ['set',  'tech_groups',               '',                    '',             2],
        ['set',  'tech_annual',               '',                    '',             0],
        ['set',  'tech_variable',             '',                    '',             0],
        ['set',  'tech_retirement',           '',                    '',             0],
        ['set',  'groups',                    '',                    '',             0],
        ['param','LinkedTechs',               '',                    '',             3],
        ['param','SegFrac',                   '',                    '',             2],
        ['param','DemandSpecificDistribution','',                    '',             4],
        ['param','CapacityToActivity',        '',                    '',             2],
        ['param','PlanningReserveMargin',     '',                    '',             1],
        ['param','GlobalDiscountRate',        '',                    '',             0],
        ['param','MyopicBaseyear',            '',                    '',             0],
        ['param','LoanRate',              '',                    '',             3],
        ['param','EmissionActivity',          '',                    '',             6],
        ['param','EmissionLimit',             '',                    '',             3],
        ['param','Demand',                    '',                    '',             3],
        ['param','TechOutputSplit',           '',                    '',             4],
        ['param','TechInputSplit',            '',                    '',             4],
        ['param','TechInputSplitAverage',     '',                    '',             4],
        ['param','MinCapacity',               '',                    '',             3],
        ['param','MaxCapacity',               '',                    '',             3],
        ['param','MinNewCapacity',            '',                    '',             3],
        ['param','MaxNewCapacity',            '',                    '',             3],
        ['param','MaxActivity',               '',                    '',             3],
        ['param','MinActivity',               '',                    '',             3],
        ['param','RenewablePortfolioStandard','',                    '',             2],
        ['param','MinAnnualCapacityFactor',   '',                    '',             4],
        ['param','MaxAnnualCapacityFactor',   '',                    '',             4],
        ['param','MinActivityGroup',          '',                    '',             3],
        ['param','MaxActivityGroup',          '',                    '',             3],
        ['param','MinCapacityGroup',          '',                    '',             3],
        ['param','MaxCapacityGroup',          '',                    '',             3],
        ['param','MinNewCapacityGroup',       '',                    '',             3],
        ['param','MaxNewCapacityGroup',       '',                    '',             3],
        ['param','MinActivityShare',          '',                    '',             4],
        ['param','MaxActivityShare',          '',                    '',             4],
        ['param','MinCapacityShare',          '',                    '',             4],
        ['param','MaxCapacityShare',          '',                    '',             4],
        ['param','MinNewCapacityShare',       '',                    '',             4],
        ['param','MaxNewCapacityShare',       '',                    '',             4],
        ['param','MaxResource',               '',                    '',             2],
        ['param','GrowthRateMax',             '',                    '',             2],
        ['param','GrowthRateSeed',            '',                    '',             2],
        ['param','LifetimeTech',              '',                    '',             2],
        ['param','LifetimeProcess',           '',                    '',             3],
        ['param','LifetimeLoanTech',          '',                    '',             2],
        ['param','CapacityFactorTech',        '',                    '',             4],
        ['param','CapacityFactorProcess',     '',                    '',             5],
        ['param','Efficiency',                '',                    '',             5],
        ['param','ExistingCapacity',          '',                    '',             3],
        ['param','CostInvest',                '',                    '',             3],
        ['param','CostFixed',                 '',                    '',             4],
        ['param','CostVariable',              '',                    '',             4],
        ['param','CapacityCredit',            '',                    '',             4],
        ['param','RampUp',                    '',                    '',             2],
        ['param','RampDown',                  '',                    '',             2],
        ['param','StorageInitFrac',           '',                    '',             3],
        ['param','StorageDuration',           '',                    '',             2]]

    with open(ofile, 'w') as f:
        f.write('data ;\n\n')
        # connect to the database
        con = sqlite3.connect(ifile, isolation_level=None)
        cur = con.cursor()  # a database cursor is a control structure that enables traversal over the records in a database
        con.text_factory = str  # this ensures data is explored with the correct UTF-8 encoding

        # Return the full list of existing tables.
        table_exist = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_exist = [i[0] for i in table_exist]

        for table in table_list:
            if table[1] in table_exist:
                query_table(table, f)
        if options.scenario_mode == TemoaMode.MGA:
            raise NotImplementedError('mga stuff to do...')
            # if options.mga_weight == 'integer':
            #     write_tech_mga(f)
            # if options.mga_weight == 'normalized':
            #     write_tech_sector(f)

        # construct the RegionalGlobalIndices Set
        construct_RegionalGlobalIndices(tables_in_db=table_exist, f=f)

        # Making sure the database is empty from the begining for a myopic solve
        if options.scenario_mode == TemoaMode.MYOPIC:
            cur.execute(
                "DELETE FROM OutputNetCapacity WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM OutputEmission WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM OutputCost WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM OutputObjective WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM OutputFlowIn WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM OutputFlowOut WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM OutputNetCapacity WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM OutputBuiltCapacity WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM OutputRetiredCapacity WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM OutputCurtailment WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM OutputDualVariable WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("VACUUM")
            con.commit()

        cur.close()
        con.close()

    logger.debug('Finished creation of .dat file')
