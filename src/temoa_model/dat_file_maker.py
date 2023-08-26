"""
The purpose of this file is to create pyomo .dat files from the input database.

The contents of this file were originally contained in the temoa_config module and have been separated here
"""


def db_2_dat(ifile, ofile, options):
    # Adapted from DB_to_DAT.py
    import sqlite3
    import re

    def write_tech_mga(f):
        cur.execute("SELECT tech FROM technologies")
        f.write("set tech_mga :=\n")
        for row in cur:
            f.write(row[0] + '\n')
        f.write(';\n\n')

    def write_tech_sector(f):
        sectors = set()
        cur.execute("SELECT sector FROM technologies")
        for row in cur:
            sectors.add(row[0])
        for s in sectors:
            cur.execute("SELECT tech FROM technologies WHERE sector == '" + s + "'")
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
                print(str_row)
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
                print(str_row)
        f.write(';\n\n')

    # [set or param, table_name, DAT fieldname, flag (if any), index (where to insert '#')
    table_list = [
        ['set', 'time_periods', 'time_exist', 'e', 0],
        ['set', 'time_periods', 'time_future', 'f', 0],
        ['set', 'time_season', '', '', 0],
        ['set', 'time_of_day', '', '', 0],
        ['set', 'regions', '', '', 0],
        ['set', 'tech_curtailment', '', '', 0],
        ['set', 'tech_flex', '', '', 0],
        ['set', 'tech_reserve', '', '', 0],
        ['set', 'technologies', 'tech_resource', 'r', 0],
        ['set', 'technologies', 'tech_production', ['p', 'pb', 'ps'], 0],
        ['set', 'technologies', 'tech_baseload', 'pb', 0],
        ['set', 'technologies', 'tech_storage', 'ps', 0],
        ['set', 'tech_ramping', '', '', 0],
        ['set', 'tech_exchange', '', '', 0],
        ['set', 'commodities', 'commodity_physical', 'p', 0],
        ['set', 'commodities', 'commodity_emissions', 'e', 0],
        ['set', 'commodities', 'commodity_demand', 'd', 0],
        ['set', 'tech_groups', '', '', 0],
        ['set', 'tech_annual', '', '', 0],
        ['set', 'tech_variable', '', '', 0],
        ['set', 'groups', '', '', 0],
        ['param', 'MinGenGroupTarget', '', '', 2],
        ['param', 'MinGenGroupWeight', '', '', 3],
        ['param', 'LinkedTechs', '', '', 3],
        ['param', 'SegFrac', '', '', 2],
        ['param', 'DemandSpecificDistribution', '', '', 4],
        ['param', 'CapacityToActivity', '', '', 2],
        ['param', 'PlanningReserveMargin', '', '', 2],
        ['param', 'GlobalDiscountRate', '', '', 0],
        ['param', 'MyopicBaseyear', '', '', 0],
        ['param', 'DiscountRate', '', '', 3],
        ['param', 'EmissionActivity', '', '', 6],
        ['param', 'EmissionLimit', '', '', 3],
        ['param', 'Demand', '', '', 3],
        ['param', 'TechOutputSplit', '', '', 4],
        ['param', 'TechInputSplit', '', '', 4],
        ['param', 'TechInputSplitAverage', '', '', 4],
        ['param', 'MinCapacity', '', '', 3],
        ['param', 'MaxCapacity', '', '', 3],
        ['param', 'MaxActivity', '', '', 3],
        ['param', 'MinActivity', '', '', 3],
        ['param', 'MaxResource', '', '', 2],
        ['param', 'GrowthRateMax', '', '', 2],
        ['param', 'GrowthRateSeed', '', '', 2],
        ['param', 'LifetimeTech', '', '', 2],
        ['param', 'LifetimeProcess', '', '', 3],
        ['param', 'LifetimeLoanTech', '', '', 2],
        ['param', 'CapacityFactorTech', '', '', 4],
        ['param', 'CapacityFactorProcess', '', '', 5],
        ['param', 'Efficiency', '', '', 5],
        ['param', 'ExistingCapacity', '', '', 3],
        ['param', 'CostInvest', '', '', 3],
        ['param', 'CostFixed', '', '', 4],
        ['param', 'CostVariable', '', '', 4],
        ['param', 'CapacityCredit', '', '', 4],
        ['param', 'RampUp', '', '', 2],
        ['param', 'RampDown', '', '', 2],
        ['param', 'StorageInitFrac', '', '', 3],
        ['param', 'StorageDuration', '', '', 2]]

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
        if options.mga_weight == 'integer':
            write_tech_mga(f)
        if options.mga_weight == 'normalized':
            write_tech_sector(f)

        # Making sure the database is empty from the begining for a myopic solve
        if options.myopic:
            cur.execute(
                "DELETE FROM Output_CapacityByPeriodAndTech WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM Output_Emissions WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM Output_Costs WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM Output_Objective WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM Output_VFlow_In WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM Output_VFlow_Out WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM Output_V_Capacity WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM Output_Curtailment WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("DELETE FROM Output_Duals WHERE scenario=" + "'" + str(options.scenario) + "'")
            cur.execute("VACUUM")
            con.commit()

        cur.close()
        con.close()
