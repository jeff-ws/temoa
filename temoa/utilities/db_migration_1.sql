-- add the unlimited capacity flag to the technologies table
ALTER TABLE technologies
    ADD unlim_cap INTEGER;

-- update the commodity flags.  REPLACE acts like "insert if not already there..."
REPLACE INTO main.commodity_labels
VALUES ('s', 'source commodity');

-- fix the FK assignment in OutputEmissions to ref the commodity table.  (the old ref was not a unique index)
CREATE TABLE Output_Emissions_dg_tmp
(
    regions        text,
    scenario       text,
    sector         text,
    t_periods      integer,
    emissions_comm text,
    tech           text,
    vintage        integer,
    emissions      real,
    PRIMARY KEY (regions, scenario, t_periods, emissions_comm, tech, vintage),
    FOREIGN KEY (sector) REFERENCES sector_labels,
    FOREIGN KEY (t_periods) REFERENCES time_periods,
    FOREIGN KEY (emissions_comm) REFERENCES commodities,
    FOREIGN KEY (tech) REFERENCES technologies,
    FOREIGN KEY (vintage) REFERENCES time_periods
);

INSERT INTO Output_Emissions_dg_tmp(regions, scenario, sector, t_periods, emissions_comm, tech, vintage, emissions)
SELECT regions,
       scenario,
       sector,
       t_periods,
       emissions_comm,
       tech,
       vintage,
       emissions
FROM Output_Emissions;

DROP TABLE Output_Emissions;

ALTER TABLE Output_Emissions_dg_tmp
    RENAME TO Output_Emissions;

CREATE TABLE IF NOT EXISTS Output_Costs_2
(
    scenario text,
    region   text,
    period   integer,
    tech     text,
    vintage  integer,
    d_invest real,
    d_fixed  real,
    d_var    real,
    invest   real,
    fixed    real,
    var      real,

    FOREIGN KEY (vintage) REFERENCES time_periods (t_periods),
    FOREIGN KEY (tech) REFERENCES technologies (tech),

    PRIMARY KEY (scenario, region, period, tech, vintage)
);

-- turn on FK enforcement
PRAGMA FOREIGN_KEYS = 1;



