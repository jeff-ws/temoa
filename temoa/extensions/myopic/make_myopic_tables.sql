BEGIN;

CREATE TABLE IF NOT EXISTS MyopicNetCapacity
(
    basis_year integer,
    region     text,
    period     integer,
    sector     text,
    tech       text,
    vintage    integer,
    capacity   real,
    lifetime   integer,

    FOREIGN KEY (sector) REFERENCES sector_labels (sector),
    FOREIGN KEY (vintage) REFERENCES time_periods (t_periods),
    FOREIGN KEY (tech) REFERENCES technologies (tech),

    PRIMARY KEY (region, period, tech, vintage),
    CHECK ( capacity >= 0 )
);

CREATE TABLE IF NOT EXISTS MyopicEfficiency
(
    base_year   integer,
    region      text,
    input_comm  text,
    tech        text,
    vintage     integer,
    output_comm text,
    efficiency  real,
    lifetime    integer,

    FOREIGN KEY (tech) REFERENCES technologies (tech),
    FOREIGN KEY (region) REFERENCES regions (regions),

    PRIMARY KEY (region, input_comm, tech, vintage, output_comm)
);
-- for efficient searching by rtv:
CREATE INDEX IF NOT EXISTS region_tech_vintage ON MyopicEfficiency (region, tech, vintage);
-- CREATE TABLE IF NOT EXISTS MyopicEmission (
--     scenario    text,
--     region      text,
--     sector      text,
--     period      integer,
--     emission_commodity  text,
--     tech        text,
--     vintage     integer,
--     emission_qty    real,
--
--     FOREIGN KEY (period) REFERENCES time_periods(t_periods),
--     FOREIGN KEY (sector) REFERENCES sector_labels(sector),
--     FOREIGN KEY (vintage) REFERENCES time_periods(t_periods),
--     FOREIGN KEY (tech)  REFERENCES technologies(tech),
--     FOREIGN KEY (emission_commodity) REFERENCES commodities(comm_name),
--
--     PRIMARY KEY (scenario,region, period, emission_commodity, tech, vintage)
-- );
-- CREATE TABLE IF NOT EXISTS MyopicCurtailment (
--     scenario    text,
--     region      text,
--     sector      text,
--     period      integer,
--     season      text,
--     t_day       text,
--     input_comm  text,
--     tech        text,
--     vintage     integer,
--     output_comm integer,
--     curtailment real,
--
--     FOREIGN KEY (period) REFERENCES time_periods(t_periods),
--     FOREIGN KEY (sector) REFERENCES sector_labels(sector),
--     FOREIGN KEY (vintage) REFERENCES time_periods(t_periods),
--     FOREIGN KEY (tech)  REFERENCES technologies(tech),
--     FOREIGN KEY (output_comm) REFERENCES commodities(comm_name),
--     FOREIGN KEY (input_comm) REFERENCES commodities(comm_name),
--     FOREIGN KEY (t_day) REFERENCES time_of_day(t_day),
--     FOREIGN KEY (season) REFERENCES time_season(t_season),
--
--     PRIMARY KEY (region, scenario, period, season, t_day, input_comm, tech, vintage, output_comm)
--
-- );
-- CREATE TABLE IF NOT EXISTS MyopicCost
-- (
--     scenario    text,
--     region      text,
--     sector      text,
--     period      integer,
--     output_name text,
--     tech        text,
--     vintage     integer,
--     cost        real,
--
--     FOREIGN KEY (sector) REFERENCES sector_labels (sector),
--     FOREIGN KEY (region) REFERENCES regions (regions),
--     FOREIGN KEY (tech) REFERENCES technologies (tech),
--     FOREIGN KEY (vintage) REFERENCES time_periods (t_periods),
--     FOREIGN KEY (period) REFERENCES time_periods (t_periods),
--
--     PRIMARY KEY (region, scenario, output_name, tech, vintage)
--
-- );
-- CREATE TABLE IF NOT EXISTS MyopicRetirement (
--     scenario    text,
--     region      text,
--     sector      text,
--     period      text,
--     tech        text,
--     vintage     integer,
--     capacity    real,
--
--     FOREIGN KEY (period) REFERENCES time_periods(t_periods),
--     FOREIGN KEY (sector) REFERENCES sector_labels(sector),
--     FOREIGN KEY (region) REFERENCES regions(regions),
--     FOREIGN KEY (tech) REFERENCES technologies(tech),
--     FOREIGN KEY (vintage) REFERENCES time_periods(t_periods),
--
--     PRIMARY KEY (region, scenario, period, tech, vintage)
-- );

-- CREATE TABLE IF NOT EXISTS MyopicFlowIn(
--     scenario    text,
--     region      text,
--     sector      text,
--     period      text,
--     season      text,
--     t_day       text,
--     input_comm  text,
--     tech        text,
--     vintage     integer,
--     output_comm text,
--     flow        real,
--
--     FOREIGN KEY (period) REFERENCES time_periods(t_periods),
--     FOREIGN KEY (sector) REFERENCES sector_labels(sector),
--     FOREIGN KEY (region) REFERENCES regions(regions),
--     FOREIGN KEY (tech) REFERENCES technologies(tech),
--     FOREIGN KEY (vintage) REFERENCES time_periods(t_periods),
--     FOREIGN KEY (input_comm) REFERENCES commodities(comm_name),
--     FOREIGN KEY (output_comm) REFERENCES commodities(comm_name),
--     FOREIGN KEY (season) REFERENCES time_season(t_season),
--     FOREIGN KEY (t_day) REFERENCES time_of_day(t_day),
--
--     PRIMARY KEY (region, scenario, period, season, t_day, input_comm, tech, vintage, output_comm),
--     check ( flow >= 0 )
-- );
-- CREATE TABLE IF NOT EXISTS MyopicFlowOut(
--     scenario    text,
--     region      text,
--     sector      text,
--     period      text,
--     season      text,
--     t_day       text,
--     input_comm  text,
--     tech        text,
--     vintage     integer,
--     output_comm text,
--     flow        real,
--
--     FOREIGN KEY (period) REFERENCES time_periods(t_periods),
--     FOREIGN KEY (sector) REFERENCES sector_labels(sector),
--     FOREIGN KEY (region) REFERENCES regions(regions),
--     FOREIGN KEY (tech) REFERENCES technologies(tech),
--     FOREIGN KEY (vintage) REFERENCES time_periods(t_periods),
--     FOREIGN KEY (input_comm) REFERENCES commodities(comm_name),
--     FOREIGN KEY (output_comm) REFERENCES commodities(comm_name),
--     FOREIGN KEY (season) REFERENCES time_season(t_season),
--     FOREIGN KEY (t_day) REFERENCES time_of_day(t_day),
--
--     PRIMARY KEY (region, scenario, period, season, t_day, input_comm, tech, vintage, output_comm),
--     check ( flow >= 0 )
-- );

COMMIT;