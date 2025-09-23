PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE MetaData
(
    element TEXT,
    value   INT,
    notes   TEXT,
    PRIMARY KEY (element)
);
INSERT INTO MetaData VALUES('DB_MAJOR',3,'DB major version number');
INSERT INTO MetaData VALUES('DB_MINOR',0,'DB minor version number');
INSERT INTO MetaData VALUES('myopic_base_year',2000,'');
CREATE TABLE MetaDataReal
(
    element TEXT,
    value   REAL,
    notes   TEXT,

    PRIMARY KEY (element)
);
INSERT INTO MetaDataReal VALUES('default_loan_rate',0.05000000000000000277,'Default Loan Rate if not specified in LoanRate table');
INSERT INTO MetaDataReal VALUES('global_discount_rate',0.4199999999999999845,'');
CREATE TABLE OutputDualVariable
(
    scenario        TEXT,
    constraint_name TEXT,
    dual            REAL,
    PRIMARY KEY (constraint_name, scenario)
);
CREATE TABLE OutputObjective
(
    scenario          TEXT,
    objective_name    TEXT,
    total_system_cost REAL
);
CREATE TABLE SectorLabel
(
    sector TEXT,
    PRIMARY KEY (sector)
);
INSERT INTO SectorLabel VALUES('supply');
INSERT INTO SectorLabel VALUES('electric');
INSERT INTO SectorLabel VALUES('transport');
INSERT INTO SectorLabel VALUES('commercial');
INSERT INTO SectorLabel VALUES('residential');
INSERT INTO SectorLabel VALUES('industrial');
CREATE TABLE CapacityCredit
(
    region  TEXT,
    period  INTEGER,
    tech    TEXT,
    vintage INTEGER,
    credit  REAL,
    notes   TEXT,
    PRIMARY KEY (region, period, tech, vintage),
    CHECK (credit >= 0 AND credit <= 1)
);
INSERT INTO CapacityCredit VALUES('A',2025,'EF',2025,0.5999999999999999778,NULL);
CREATE TABLE CapacityFactorProcess
(
    region  TEXT,
    season  TEXT
        REFERENCES TimeSeason (season),
    tod     TEXT
        REFERENCES TimeOfDay (tod),
    tech    TEXT
        REFERENCES Technology (tech),
    vintage INTEGER,
    factor  REAL,
    notes   TEXT,
    PRIMARY KEY (region, season, tod, tech, vintage),
    CHECK (factor >= 0 AND factor <= 1)
);
INSERT INTO CapacityFactorProcess VALUES('A','s2','d1','EFL',2025,0.8000000000000000444,NULL);
INSERT INTO CapacityFactorProcess VALUES('A','s1','d2','EFL',2025,0.9000000000000000222,NULL);
CREATE TABLE CapacityFactorTech
(
    region TEXT,
    season TEXT
        REFERENCES TimeSeason (season),
    tod    TEXT
        REFERENCES TimeOfDay (tod),
    tech   TEXT
        REFERENCES Technology (tech),
    factor REAL,
    notes  TEXT,
    PRIMARY KEY (region, season, tod, tech),
    CHECK (factor >= 0 AND factor <= 1)
);
INSERT INTO CapacityFactorTech VALUES('A','s1','d1','EF',0.8000000000000000444,NULL);
INSERT INTO CapacityFactorTech VALUES('B','s2','d2','bulbs',0.75,NULL);
CREATE TABLE CapacityToActivity
(
    region TEXT,
    tech   TEXT
        REFERENCES Technology (tech),
    c2a    REAL,
    notes  TEXT,
    PRIMARY KEY (region, tech)
);
INSERT INTO CapacityToActivity VALUES('A','bulbs',1.0,'');
INSERT INTO CapacityToActivity VALUES('B','bulbs',1.0,NULL);
CREATE TABLE Commodity
(
    name        TEXT
        PRIMARY KEY,
    flag        TEXT
        REFERENCES CommodityType (label),
    description TEXT
);
INSERT INTO Commodity VALUES('ELC','p','electricity');
INSERT INTO Commodity VALUES('HYD','p','water');
INSERT INTO Commodity VALUES('co2','e','CO2 emissions');
INSERT INTO Commodity VALUES('RL','d','residential lighting');
INSERT INTO Commodity VALUES('earth','p','the source of stuff');
INSERT INTO Commodity VALUES('RH','d','residential heat');
INSERT INTO Commodity VALUES('FusionGas','e','mystery emission');
INSERT INTO Commodity VALUES('FusionGasFuel','p','converted mystery gas to fuel');
INSERT INTO Commodity VALUES('GeoHyd','p','Hot water from geo');
CREATE TABLE CommodityType
(
    label       TEXT
        PRIMARY KEY,
    description TEXT
);
INSERT INTO CommodityType VALUES('p','physical commodity');
INSERT INTO CommodityType VALUES('e','emissions commodity');
INSERT INTO CommodityType VALUES('d','demand commodity');
INSERT INTO CommodityType VALUES('s','source commodity');
CREATE TABLE CostEmission
(
    region    TEXT
        REFERENCES Region (region),
    period    INTEGER
        REFERENCES TimePeriod (period),
    emis_comm TEXT NOT NULL
        REFERENCES Commodity (name),
    cost      REAL NOT NULL,
    units     TEXT,
    notes     TEXT,
    PRIMARY KEY (region, period, emis_comm)
);
INSERT INTO CostEmission VALUES ('A', 2025, 'co2', 1.99, 'dollars', 'none' );
CREATE TABLE CostFixed
(
    region  TEXT    NOT NULL,
    period  INTEGER NOT NULL
        REFERENCES TimePeriod (period),
    tech    TEXT    NOT NULL
        REFERENCES Technology (tech),
    vintage INTEGER NOT NULL
        REFERENCES TimePeriod (period),
    cost    REAL,
    units   TEXT,
    notes   TEXT,
    PRIMARY KEY (region, period, tech, vintage)
);
INSERT INTO CostFixed VALUES('A',2025,'EH',2025,3.299999999999999823,'','');
INSERT INTO CostFixed VALUES('A',2025,'EF',2025,2.0,NULL,NULL);
INSERT INTO CostFixed VALUES('A',2025,'EFL',2025,3.0,NULL,NULL);
INSERT INTO CostFixed VALUES('B',2025,'batt',2025,1.0,NULL,NULL);
INSERT INTO CostFixed VALUES('B',2025,'EF',2025,2.0,NULL,NULL);
INSERT INTO CostFixed VALUES('A',2025,'bulbs',2025,1.0,NULL,NULL);
INSERT INTO CostFixed VALUES('B',2025,'bulbs',2025,1.0,NULL,NULL);
INSERT INTO CostFixed VALUES('A',2025,'heater',2025,2.0,NULL,NULL);
INSERT INTO CostFixed VALUES('B',2025,'heater',2025,2.0,NULL,NULL);
INSERT INTO CostFixed VALUES('B',2025,'GeoThermal',2025,6.0,NULL,NULL);
INSERT INTO CostFixed VALUES('B',2025,'GeoHeater',2025,1.0,NULL,NULL);
INSERT INTO CostFixed VALUES('B',2025,'EH',2025,3.299999999999999823,NULL,NULL);
INSERT INTO CostFixed VALUES('A',2025,'GeoThermal',2025,4.0,NULL,NULL);
INSERT INTO CostFixed VALUES('A',2025,'GeoHeater',2025,4.5,NULL,NULL);
CREATE TABLE CostInvest
(
    region  TEXT,
    tech    TEXT
        REFERENCES Technology (tech),
    vintage INTEGER
        REFERENCES TimePeriod (period),
    cost    REAL,
    units   TEXT,
    notes   TEXT,
    PRIMARY KEY (region, tech, vintage)
);
INSERT INTO CostInvest VALUES('A','EF',2025,1.0,NULL,NULL);
INSERT INTO CostInvest VALUES('A','EH',2025,3.0,NULL,NULL);
INSERT INTO CostInvest VALUES('A','bulbs',2025,4.0,NULL,NULL);
INSERT INTO CostInvest VALUES('A','heater',2025,5.0,NULL,NULL);
INSERT INTO CostInvest VALUES('B','EF',2025,6.0,NULL,NULL);
INSERT INTO CostInvest VALUES('B','batt',2025,7.0,NULL,NULL);
INSERT INTO CostInvest VALUES('B','bulbs',2025,8.0,NULL,NULL);
INSERT INTO CostInvest VALUES('B','heater',2025,9.0,NULL,NULL);
INSERT INTO CostInvest VALUES('A','EFL',2025,2.0,NULL,NULL);
INSERT INTO CostInvest VALUES('B','GeoThermal',2025,3.0,NULL,NULL);
INSERT INTO CostInvest VALUES('B','GeoHeater',2025,4.0,NULL,NULL);
INSERT INTO CostInvest VALUES('B','EH',2025,3.299999999999999823,NULL,NULL);
INSERT INTO CostInvest VALUES('A','GeoThermal',2025,5.599999999999999645,NULL,NULL);
INSERT INTO CostInvest VALUES('A','GeoHeater',2025,4.200000000000000177,NULL,NULL);
CREATE TABLE CostVariable
(
    region  TEXT    NOT NULL,
    period  INTEGER NOT NULL
        REFERENCES TimePeriod (period),
    tech    TEXT    NOT NULL
        REFERENCES Technology (tech),
    vintage INTEGER NOT NULL
        REFERENCES TimePeriod (period),
    cost    REAL,
    units   TEXT,
    notes   TEXT,
    PRIMARY KEY (region, period, tech, vintage)
);
INSERT INTO CostVariable VALUES('A',2025,'EF',2025,9.0,NULL,NULL);
INSERT INTO CostVariable VALUES('A',2025,'EFL',2025,8.0,NULL,NULL);
INSERT INTO CostVariable VALUES('A',2025,'EH',2025,7.0,NULL,NULL);
INSERT INTO CostVariable VALUES('A',2025,'bulbs',2025,6.0,NULL,NULL);
INSERT INTO CostVariable VALUES('A',2025,'heater',2025,5.0,NULL,NULL);
INSERT INTO CostVariable VALUES('B',2025,'EF',2025,4.0,NULL,NULL);
INSERT INTO CostVariable VALUES('B',2025,'batt',2025,3.0,NULL,NULL);
INSERT INTO CostVariable VALUES('B',2025,'bulbs',2025,2.0,NULL,NULL);
INSERT INTO CostVariable VALUES('B',2025,'heater',2025,1.0,NULL,NULL);
CREATE TABLE Demand
(
    region    TEXT,
    period    INTEGER
        REFERENCES TimePeriod (period),
    commodity TEXT
        REFERENCES Commodity (name),
    demand    REAL,
    units     TEXT,
    notes     TEXT,
    PRIMARY KEY (region, period, commodity)
);
INSERT INTO Demand VALUES('A',2025,'RL',100.0,'','');
INSERT INTO Demand VALUES('B',2025,'RL',100.0,NULL,NULL);
INSERT INTO Demand VALUES('A',2025,'RH',50.0,NULL,NULL);
INSERT INTO Demand VALUES('B',2025,'RH',50.0,NULL,NULL);
CREATE TABLE DemandSpecificDistribution
(
    region      TEXT,
    season      TEXT
        REFERENCES TimeSeason (season),
    tod         TEXT
        REFERENCES TimeOfDay (tod),
    demand_name TEXT
        REFERENCES Commodity (name),
    dds         REAL,
    dds_notes   TEXT,
    PRIMARY KEY (region, season, tod, demand_name),
    CHECK (dds >= 0 AND dds <= 1)
);
INSERT INTO DemandSpecificDistribution VALUES('A','s1','d1','RL',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('A','s1','d2','RL',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('A','s2','d1','RL',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('A','s2','d2','RL',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('B','s1','d1','RL',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('B','s1','d2','RL',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('B','s2','d1','RL',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('B','s2','d2','RL',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('A','s1','d1','RH',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('A','s2','d1','RH',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('B','s1','d1','RH',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('B','s2','d1','RH',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('A','s1','d2','RH',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('A','s2','d2','RH',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('B','s1','d2','RH',0.25,NULL);
INSERT INTO DemandSpecificDistribution VALUES('B','s2','d2','RH',0.25,NULL);
CREATE TABLE LoanRate
(
    region  TEXT,
    tech    TEXT
        REFERENCES Technology (tech),
    vintage INTEGER
        REFERENCES TimePeriod (period),
    rate    REAL,
    notes   TEXT,
    PRIMARY KEY (region, tech, vintage)
);
CREATE TABLE Efficiency
(
    region      TEXT,
    input_comm  TEXT
        REFERENCES Commodity (name),
    tech        TEXT
        REFERENCES Technology (tech),
    vintage     INTEGER
        REFERENCES TimePeriod (period),
    output_comm TEXT
        REFERENCES Commodity (name),
    efficiency  REAL,
    notes       TEXT,
    PRIMARY KEY (region, input_comm, tech, vintage, output_comm),
    CHECK (efficiency > 0)
);
INSERT INTO Efficiency VALUES('A','ELC','bulbs',2025,'RL',1.0,NULL);
INSERT INTO Efficiency VALUES('A','HYD','EH',2025,'ELC',1.0,NULL);
INSERT INTO Efficiency VALUES('A','HYD','EF',2025,'ELC',1.0,NULL);
INSERT INTO Efficiency VALUES('B','ELC','bulbs',2025,'RL',1.0,NULL);
INSERT INTO Efficiency VALUES('B','HYD','EH',2025,'ELC',1.0,NULL);
INSERT INTO Efficiency VALUES('B','ELC','batt',2025,'ELC',1.0,NULL);
INSERT INTO Efficiency VALUES('B','HYD','EF',2025,'ELC',1.0,NULL);
INSERT INTO Efficiency VALUES('A','earth','well',2025,'HYD',1.0,NULL);
INSERT INTO Efficiency VALUES('B','earth','well',2025,'HYD',1.0,NULL);
INSERT INTO Efficiency VALUES('A','earth','EFL',2025,'FusionGasFuel',1.0,NULL);
INSERT INTO Efficiency VALUES('A','FusionGasFuel','heater',2025,'RH',0.9000000000000000222,NULL);
INSERT INTO Efficiency VALUES('A-B','FusionGasFuel','FGF_pipe',2025,'FusionGasFuel',0.949999999999999956,NULL);
INSERT INTO Efficiency VALUES('B','FusionGasFuel','heater',2025,'RH',0.9000000000000000222,NULL);
INSERT INTO Efficiency VALUES('B','GeoHyd','GeoHeater',2025,'RH',0.979999999999999983,NULL);
INSERT INTO Efficiency VALUES('B','earth','GeoThermal',2025,'GeoHyd',1.0,NULL);
INSERT INTO Efficiency VALUES('B-A','FusionGasFuel','FGF_pipe',2025,'FusionGasFuel',0.949999999999999956,NULL);
INSERT INTO Efficiency VALUES('A','GeoHyd','GeoHeater',2025,'RH',0.9000000000000000222,NULL);
INSERT INTO Efficiency VALUES('A','earth','GeoThermal',2025,'GeoHyd',1.0,NULL);
CREATE TABLE EmissionActivity
(
    region      TEXT,
    emis_comm   TEXT
        REFERENCES Commodity (name),
    input_comm  TEXT
        REFERENCES Commodity (name),
    tech        TEXT
        REFERENCES Technology (tech),
    vintage     INTEGER
        REFERENCES TimePeriod (period),
    output_comm TEXT
        REFERENCES Commodity (name),
    activity    REAL,
    units       TEXT,
    notes       TEXT,
    PRIMARY KEY (region, emis_comm, input_comm, tech, vintage, output_comm)
);
INSERT INTO EmissionActivity VALUES('A','co2','HYD','EH',2025,'ELC',0.02000000000000000041,NULL,NULL);
INSERT INTO EmissionActivity VALUES('A','FusionGas','HYD','EF',2025,'ELC',-0.2000000000000000111,NULL,'needs to be negative as a driver of linked tech...don''t ask');
CREATE TABLE ExistingCapacity
(
    region   TEXT,
    tech     TEXT
        REFERENCES Technology (tech),
    vintage  INTEGER
        REFERENCES TimePeriod (period),
    capacity REAL,
    units    TEXT,
    notes    TEXT,
    PRIMARY KEY (region, tech, vintage)
);
INSERT INTO ExistingCapacity VALUES('A','EH',2020,200.0,'things',NULL);
CREATE TABLE TechGroup
(
    group_name TEXT
        PRIMARY KEY,
    notes      TEXT
);
INSERT INTO TechGroup VALUES('RPS_global','');
INSERT INTO TechGroup VALUES('RPS_common','');
INSERT INTO TechGroup VALUES('(A)_tech_grp_1','converted from old db');
CREATE TABLE GrowthRateMax
(
    region TEXT,
    tech   TEXT
        REFERENCES Technology (tech),
    rate   REAL,
    notes  TEXT,
    PRIMARY KEY (region, tech)
);
INSERT INTO GrowthRateMax VALUES('A','GeoHeater',0.2000000000000000111,NULL);
CREATE TABLE GrowthRateSeed
(
    region TEXT,
    tech   TEXT
        REFERENCES Technology (tech),
    seed   REAL,
    units  TEXT,
    notes  TEXT,
    PRIMARY KEY (region, tech)
);
INSERT INTO GrowthRateSeed VALUES('A','GeoHeater',1000.0,'jobs','unk');
CREATE TABLE LoanLifetimeTech
(
    region   TEXT,
    tech     TEXT
        REFERENCES Technology (tech),
    lifetime REAL,
    notes    TEXT,
    PRIMARY KEY (region, tech)
);
INSERT INTO LoanLifetimeTech VALUES('A','EF',57.0,NULL);
INSERT INTO LoanLifetimeTech VALUES('A','EFL',68.0,NULL);
CREATE TABLE LifetimeProcess
(
    region   TEXT,
    tech     TEXT
        REFERENCES Technology (tech),
    vintage  INTEGER
        REFERENCES TimePeriod (period),
    lifetime REAL,
    notes    TEXT,
    PRIMARY KEY (region, tech, vintage)
);
INSERT INTO LifetimeProcess VALUES('B','EF',2025,200.0,NULL);
CREATE TABLE LifetimeTech
(
    region   TEXT,
    tech     TEXT
        REFERENCES Technology (tech),
    lifetime REAL,
    notes    TEXT,
    PRIMARY KEY (region, tech)
);
INSERT INTO LifetimeTech VALUES('A','EH',60.0,'');
INSERT INTO LifetimeTech VALUES('B','bulbs',100.0,'super LED!');
CREATE TABLE LinkedTech
(
    primary_region TEXT,
    primary_tech   TEXT
        REFERENCES Technology (tech),
    emis_comm      TEXT
        REFERENCES Commodity (name),
    driven_tech    TEXT
        REFERENCES Technology (tech),
    notes          TEXT,
    PRIMARY KEY (primary_region, primary_tech, emis_comm)
);
INSERT INTO LinkedTech VALUES('A','EF','FusionGas','EFL',NULL);
CREATE TABLE MaxActivity
(
    region  TEXT,
    period  INTEGER
        REFERENCES TimePeriod (period),
    tech    TEXT
        REFERENCES Technology (tech),
    max_act REAL,
    units   TEXT,
    notes   TEXT,
    PRIMARY KEY (region, period, tech)
);
INSERT INTO MaxActivity VALUES('B',2025,'EH',10000.0,'stuff',NULL);
INSERT INTO MaxActivity VALUES('A',2025,'EF',10000.0,'stuff',NULL);
CREATE TABLE MaxCapacity
(
    region  TEXT,
    period  INTEGER
        REFERENCES TimePeriod (period),
    tech    TEXT
        REFERENCES Technology (tech),
    max_cap REAL,
    units   TEXT,
    notes   TEXT,
    PRIMARY KEY (region, period, tech)
);
INSERT INTO MaxCapacity VALUES('A',2025,'EH',20000.0,'','');
INSERT INTO MaxCapacity VALUES('B',2025,'EH',20000.0,'','');
CREATE TABLE MaxResource
(
    region  TEXT,
    tech    TEXT
        REFERENCES Technology (tech),
    max_res REAL,
    units   TEXT,
    notes   TEXT,
    PRIMARY KEY (region, tech)
);
INSERT INTO MaxResource VALUES('B','EF',9000.0,'clumps',NULL);
CREATE TABLE MinActivity
(
    region  TEXT,
    period  INTEGER
        REFERENCES TimePeriod (period),
    tech    TEXT
        REFERENCES Technology (tech),
    min_act REAL,
    units   TEXT,
    notes   TEXT,
    PRIMARY KEY (region, period, tech)
);
INSERT INTO MinActivity VALUES('A',2025,'EF',0.00100000000000000002,'PJ/CY','goofy units');
CREATE TABLE MaxCapacityGroup
(
    region     TEXT,
    period     INTEGER
        REFERENCES TimePeriod (period),
    group_name TEXT
        REFERENCES TechGroup (group_name),
    max_cap    REAL,
    units      TEXT,
    notes      TEXT,
    PRIMARY KEY (region, period, group_name)
);
INSERT INTO MaxCapacityGroup VALUES('A',2025,'(A)_tech_grp_1',6000.0,'',NULL);
CREATE TABLE MinCapacity
(
    region  TEXT,
    period  INTEGER
        REFERENCES TimePeriod (period),
    tech    TEXT
        REFERENCES Technology (tech),
    min_cap REAL,
    units   TEXT,
    notes   TEXT,
    PRIMARY KEY (region, period, tech)
);
INSERT INTO MinCapacity VALUES('A',2025,'EH',0.1000000000000000055,'','');
INSERT INTO MinCapacity VALUES('B',2025,'batt',0.1000000000000000055,'','');
CREATE TABLE MinCapacityGroup
(
    region     TEXT,
    period     INTEGER
        REFERENCES TimePeriod (period),
    group_name TEXT
        REFERENCES TechGroup (group_name),
    min_cap    REAL,
    units      TEXT,
    notes      TEXT,
    PRIMARY KEY (region, period, group_name)
);
INSERT INTO MinCapacityGroup VALUES('A',2025,'(A)_tech_grp_1',0.2000000000000000111,'',NULL);
CREATE TABLE OutputCurtailment
(
    scenario    TEXT,
    region      TEXT,
    sector      TEXT,
    period      INTEGER
        REFERENCES TimePeriod (period),
    season      TEXT
        REFERENCES TimePeriod (period),
    tod         TEXT
        REFERENCES TimeOfDay (tod),
    input_comm  TEXT
        REFERENCES Commodity (name),
    tech        TEXT
        REFERENCES Technology (tech),
    vintage     INTEGER
        REFERENCES TimePeriod (period),
    output_comm TEXT
        REFERENCES Commodity (name),
    curtailment REAL,
    PRIMARY KEY (region, scenario, period, season, tod, input_comm, tech, vintage, output_comm)
);
CREATE TABLE OutputNetCapacity
(
    scenario TEXT,
    region   TEXT,
    sector   TEXT
        REFERENCES SectorLabel (sector),
    period   INTEGER
        REFERENCES TimePeriod (period),
    tech     TEXT
        REFERENCES Technology (tech),
    vintage  INTEGER
        REFERENCES TimePeriod (period),
    capacity REAL,
    PRIMARY KEY (region, scenario, period, tech, vintage)
);
CREATE TABLE OutputBuiltCapacity
(
    scenario TEXT,
    region   TEXT,
    sector   TEXT
        REFERENCES SectorLabel (sector),
    tech     TEXT
        REFERENCES Technology (tech),
    vintage  INTEGER
        REFERENCES TimePeriod (period),
    capacity REAL,
    PRIMARY KEY (region, scenario, tech, vintage)
);
CREATE TABLE OutputRetiredCapacity
(
    scenario TEXT,
    region   TEXT,
    sector   TEXT
        REFERENCES SectorLabel (sector),
    period   INTEGER
        REFERENCES TimePeriod (period),
    tech     TEXT
        REFERENCES Technology (tech),
    vintage  INTEGER
        REFERENCES TimePeriod (period),
    capacity REAL,
    PRIMARY KEY (region, scenario, period, tech, vintage)
);
CREATE TABLE OutputFlowIn
(
    scenario    TEXT,
    region      TEXT,
    sector      TEXT
        REFERENCES SectorLabel (sector),
    period      INTEGER
        REFERENCES TimePeriod (period),
    season      TEXT
        REFERENCES TimeSeason (season),
    tod         TEXT
        REFERENCES TimeOfDay (tod),
    input_comm  TEXT
        REFERENCES Commodity (name),
    tech        TEXT
        REFERENCES Technology (tech),
    vintage     INTEGER
        REFERENCES TimePeriod (period),
    output_comm TEXT
        REFERENCES Commodity (name),
    flow        REAL,
    PRIMARY KEY (region, scenario, period, season, tod, input_comm, tech, vintage, output_comm)
);
CREATE TABLE OutputFlowOut
(
    scenario    TEXT,
    region      TEXT,
    sector      TEXT
        REFERENCES SectorLabel (sector),
    period      INTEGER
        REFERENCES TimePeriod (period),
    season      TEXT
        REFERENCES TimePeriod (period),
    tod         TEXT
        REFERENCES TimeOfDay (tod),
    input_comm  TEXT
        REFERENCES Commodity (name),
    tech        TEXT
        REFERENCES Technology (tech),
    vintage     INTEGER
        REFERENCES TimePeriod (period),
    output_comm TEXT
        REFERENCES Commodity (name),
    flow        REAL,
    PRIMARY KEY (region, scenario, period, season, tod, input_comm, tech, vintage, output_comm)
);
CREATE TABLE PlanningReserveMargin
(
    region TEXT
        PRIMARY KEY
        REFERENCES Region (region),
    margin REAL
);
INSERT INTO PlanningReserveMargin VALUES('A',0.05000000000000000277);
CREATE TABLE RampDown
(
    region TEXT,
    tech   TEXT
        REFERENCES Technology (tech),
    rate   REAL,
    PRIMARY KEY (region, tech)
);
INSERT INTO RampDown VALUES('A','EH',0.2000000000000000111);
INSERT INTO RampDown VALUES('B','EH',0.2000000000000000111);
CREATE TABLE RampUp
(
    region TEXT,
    tech   TEXT
        REFERENCES Technology (tech),
    rate   REAL,
    PRIMARY KEY (region, tech)
);
INSERT INTO RampUp VALUES('B','EH',100.0);
INSERT INTO RampUp VALUES('A','EH',100.0);
CREATE TABLE Region
(
    region TEXT
        PRIMARY KEY,
    notes  TEXT
);
INSERT INTO Region VALUES('A','main region');
INSERT INTO Region VALUES('B','just a 2nd region');
CREATE TABLE TimeSegmentFraction
(
    season  TEXT
        REFERENCES TimeSeason (season),
    tod     TEXT
        REFERENCES TimeOfDay (tod),
    segfrac REAL,
    notes   TEXT,
    PRIMARY KEY (season, tod),
    CHECK (segfrac >= 0 AND segfrac <= 1)
);
INSERT INTO TimeSegmentFraction VALUES('s2','d1',0.25,NULL);
INSERT INTO TimeSegmentFraction VALUES('s2','d2',0.25,NULL);
INSERT INTO TimeSegmentFraction VALUES('s1','d1',0.25,NULL);
INSERT INTO TimeSegmentFraction VALUES('s1','d2',0.25,NULL);
CREATE TABLE StorageDuration
(
    region   TEXT,
    tech     TEXT,
    duration REAL,
    notes    TEXT,
    PRIMARY KEY (region, tech)
);
INSERT INTO StorageDuration VALUES('B','batt',15.0,NULL);
CREATE TABLE StorageInit
(
    tech  TEXT
        PRIMARY KEY,
    value REAL,
    notes TEXT
);
CREATE TABLE TechnologyType
(
    label       TEXT
        PRIMARY KEY,
    description TEXT
);
INSERT INTO TechnologyType VALUES('r','resource technology');
INSERT INTO TechnologyType VALUES('p','production technology');
INSERT INTO TechnologyType VALUES('pb','baseload production technology');
INSERT INTO TechnologyType VALUES('ps','storage production technology');
CREATE TABLE TechInputSplit
(
    region         TEXT,
    period         INTEGER
        REFERENCES TimePeriod (period),
    input_comm     TEXT
        REFERENCES Commodity (name),
    tech           TEXT
        REFERENCES Technology (tech),
    min_proportion REAL,
    notes          TEXT,
    PRIMARY KEY (region, period, input_comm, tech)
);
INSERT INTO TechInputSplit VALUES('A',2025,'HYD','EH',0.949999999999999956,'95% HYD reqt.  (other not specified...)');
CREATE TABLE TechInputSplitAverage
(
    region         TEXT,
    period         INTEGER
        REFERENCES TimePeriod (period),
    input_comm     TEXT
        REFERENCES Commodity (name),
    tech           TEXT
        REFERENCES Technology (tech),
    min_proportion REAL,
    notes          TEXT,
    PRIMARY KEY (region, period, input_comm, tech)
);
INSERT INTO TechInputSplitAverage VALUES('A',2025,'GeoHyd','GeoHeater',0.8000000000000000444,'80% geothermal');
CREATE TABLE TechOutputSplit
(
    region         TEXT,
    period         INTEGER
        REFERENCES TimePeriod (period),
    tech           TEXT
        REFERENCES Technology (tech),
    output_comm    TEXT
        REFERENCES Commodity (name),
    min_proportion REAL,
    notes          TEXT,
    PRIMARY KEY (region, period, tech, output_comm)
);
INSERT INTO TechOutputSplit VALUES('B',2025,'EH','ELC',0.949999999999999956,'95% ELC output (there are not others, this is a min)');
CREATE TABLE TimeOfDay
(
    sequence INTEGER UNIQUE,
    tod      TEXT
        PRIMARY KEY
);
INSERT INTO TimeOfDay VALUES(1,'d1');
INSERT INTO TimeOfDay VALUES(2,'d2');
CREATE TABLE TimePeriod
(
    sequence INTEGER UNIQUE,
    period   INTEGER
        PRIMARY KEY,
    flag     TEXT
        REFERENCES TimePeriodType (label)
);
INSERT INTO TimePeriod VALUES(1,2020,'e');
INSERT INTO TimePeriod VALUES(2,2025,'f');
INSERT INTO TimePeriod VALUES(3,2030,'f');
CREATE TABLE TimeSeason
(
    sequence INTEGER UNIQUE,
    season   TEXT
        PRIMARY KEY
);
INSERT INTO TimeSeason VALUES(1,'s1');
INSERT INTO TimeSeason VALUES(2,'s2');
CREATE TABLE TimePeriodType
(
    label       TEXT
        PRIMARY KEY,
    description TEXT
);
INSERT INTO TimePeriodType VALUES('e','existing vintages');
INSERT INTO TimePeriodType VALUES('f','future');
CREATE TABLE MaxActivityShare
(
    region         TEXT,
    period         INTEGER
        REFERENCES TimePeriod (period),
    tech           TEXT
        REFERENCES Technology (tech),
    group_name     TEXT
        REFERENCES TechGroup (group_name),
    max_proportion REAL,
    notes          TEXT,
    PRIMARY KEY (region, period, tech, group_name)
);
CREATE TABLE MaxCapacityShare
(
    region         TEXT,
    period         INTEGER
        REFERENCES TimePeriod (period),
    tech           TEXT
        REFERENCES Technology (tech),
    group_name     TEXT
        REFERENCES TechGroup (group_name),
    max_proportion REAL,
    notes          TEXT,
    PRIMARY KEY (region, period, tech, group_name)
);
CREATE TABLE MaxAnnualCapacityFactor
(
    region      TEXT,
    period      INTEGER
        REFERENCES TimePeriod (period),
    tech        TEXT
        REFERENCES Technology (tech),
    output_comm TEXT
        REFERENCES Commodity (name),
    factor      REAL,
    source      TEXT,
    notes       TEXT,
    PRIMARY KEY (region, period, tech),
    CHECK (factor >= 0 AND factor <= 1)
);
CREATE TABLE MaxNewCapacity
(
    region  TEXT,
    period  INTEGER
        REFERENCES TimePeriod (period),
    tech    TEXT
        REFERENCES Technology (tech),
    max_cap REAL,
    units   TEXT,
    notes   TEXT,
    PRIMARY KEY (region, period, tech)
);
CREATE TABLE MaxNewCapacityGroup
(
    region      TEXT,
    period      INTEGER
        REFERENCES TimePeriod (period),
    group_name  TEXT
        REFERENCES TechGroup (group_name),
    max_new_cap REAL,
    units       TEXT,
    notes       TEXT,
    PRIMARY KEY (region, period, group_name)
);
CREATE TABLE MaxNewCapacityShare
(
    region         TEXT,
    period         INTEGER
        REFERENCES TimePeriod (period),
    tech           TEXT
        REFERENCES Technology (tech),
    group_name     TEXT
        REFERENCES TechGroup (group_name),
    max_proportion REAL,
    notes          TEXT,
    PRIMARY KEY (region, period, tech, group_name)
);
CREATE TABLE MinActivityShare
(
    region         TEXT,
    period         INTEGER
        REFERENCES TimePeriod (period),
    tech           TEXT
        REFERENCES Technology (tech),
    group_name     TEXT
        REFERENCES TechGroup (group_name),
    min_proportion REAL,
    notes          TEXT,
    PRIMARY KEY (region, period, tech, group_name)
);
CREATE TABLE MinAnnualCapacityFactor
(
    region      TEXT,
    period      INTEGER
        REFERENCES TimePeriod (period),
    tech        TEXT
        REFERENCES Technology (tech),
    output_comm TEXT
        REFERENCES Commodity (name),
    factor      REAL,
    source      TEXT,
    notes       TEXT,
    PRIMARY KEY (region, period, tech),
    CHECK (factor >= 0 AND factor <= 1)
);
CREATE TABLE MinCapacityShare
(
    region         TEXT,
    period         INTEGER
        REFERENCES TimePeriod (period),
    tech           TEXT
        REFERENCES Technology (tech),
    group_name     TEXT
        REFERENCES TechGroup (group_name),
    min_proportion REAL,
    notes          TEXT,
    PRIMARY KEY (region, period, tech, group_name)
);
CREATE TABLE MinNewCapacity
(
    region  TEXT,
    period  INTEGER
        REFERENCES TimePeriod (period),
    tech    TEXT
        REFERENCES Technology (tech),
    min_cap REAL,
    units   TEXT,
    notes   TEXT,
    PRIMARY KEY (region, period, tech)
);
CREATE TABLE MinNewCapacityGroup
(
    region      TEXT,
    period      INTEGER
        REFERENCES TimePeriod (period),
    group_name  TEXT
        REFERENCES TechGroup (group_name),
    min_new_cap REAL,
    units       TEXT,
    notes       TEXT,
    PRIMARY KEY (region, period, group_name)
);
CREATE TABLE MinNewCapacityShare
(
    region         TEXT,
    period         INTEGER
        REFERENCES TimePeriod (period),
    tech           TEXT
        REFERENCES Technology (tech),
    group_name     TEXT
        REFERENCES TechGroup (group_name),
    min_proportion REAL,
    notes          TEXT,
    PRIMARY KEY (region, period, tech, group_name)
);
CREATE TABLE OutputEmission
(
    scenario  TEXT,
    region    TEXT,
    sector    TEXT
        REFERENCES SectorLabel (sector),
    period    INTEGER
        REFERENCES TimePeriod (period),
    emis_comm TEXT
        REFERENCES Commodity (name),
    tech      TEXT
        REFERENCES Technology (tech),
    vintage   INTEGER
        REFERENCES TimePeriod (period),
    emission  REAL,
    PRIMARY KEY (region, scenario, period, emis_comm, tech, vintage)
);
CREATE TABLE MinActivityGroup
(
    region     TEXT,
    period     INTEGER
        REFERENCES TimePeriod (period),
    group_name TEXT
        REFERENCES TechGroup (group_name),
    min_act    REAL,
    units      TEXT,
    notes      TEXT,
    PRIMARY KEY (region, period, group_name)
);
INSERT INTO MinActivityGroup VALUES('A',2025,'(A)_tech_grp_1',0.05000000000000000277,'',NULL);
CREATE TABLE EmissionLimit
(
    region    TEXT,
    period    INTEGER
        REFERENCES TimePeriod (period),
    emis_comm TEXT
        REFERENCES Commodity (name),
    value     REAL,
    units     TEXT,
    notes     TEXT,
    PRIMARY KEY (region, period, emis_comm)
);
INSERT INTO EmissionLimit VALUES('A',2025,'co2',10000.0,'gulps',NULL);
CREATE TABLE MaxActivityGroup
(
    region     TEXT,
    period     INTEGER
        REFERENCES TimePeriod (period),
    group_name TEXT
        REFERENCES TechGroup (group_name),
    max_act    REAL,
    units      TEXT,
    notes      TEXT,
    PRIMARY KEY (region, period, group_name)
);
INSERT INTO MaxActivityGroup VALUES('A',2025,'(A)_tech_grp_1',10000.0,'',NULL);
CREATE TABLE RPSRequirement
(
    region      TEXT    NOT NULL
        REFERENCES Region (region),
    period      INTEGER NOT NULL
        REFERENCES TimePeriod (period),
    tech_group  TEXT    NOT NULL
        REFERENCES TechGroup (group_name),
    requirement REAL    NOT NULL,
    notes       TEXT
);
INSERT INTO RPSRequirement VALUES('B',2025,'RPS_common',0.2999999999999999889,NULL);
CREATE TABLE TechGroupMember
(
    group_name TEXT
        REFERENCES TechGroup (group_name),
    tech       TEXT
        REFERENCES Technology (tech),
    PRIMARY KEY (group_name, tech)
);
INSERT INTO TechGroupMember VALUES('RPS_common','EF');
INSERT INTO TechGroupMember VALUES('(A)_tech_grp_1','EH');
INSERT INTO TechGroupMember VALUES('(A)_tech_grp_1','EF');
CREATE TABLE Technology
(
    tech         TEXT    NOT NULL PRIMARY KEY,
    flag         TEXT    NOT NULL,
    sector       TEXT,
    category     TEXT,
    sub_category TEXT,
    unlim_cap    INTEGER NOT NULL DEFAULT 0,
    annual       INTEGER NOT NULL DEFAULT 0,
    reserve      INTEGER NOT NULL DEFAULT 0,
    curtail      INTEGER NOT NULL DEFAULT 0,
    retire       INTEGER NOT NULL DEFAULT 0,
    flex         INTEGER NOT NULL DEFAULT 0,
    variable     INTEGER NOT NULL DEFAULT 0,
    exchange     INTEGER NOT NULL DEFAULT 0,
    description  TEXT,
    FOREIGN KEY (flag) REFERENCES TechnologyType (label)
);
INSERT INTO Technology VALUES('well','r','supply','water','',0,0,0,0,0,0,0,0,'plain old water');
INSERT INTO Technology VALUES('bulbs','p','residential','electric','',0,0,0,0,0,0,0,0,'residential lighting');
INSERT INTO Technology VALUES('EH','pb','electric','hydro','',0,0,1,1,1,0,0,0,'hydro power electric plant');
INSERT INTO Technology VALUES('batt','ps','electric','electric','',0,0,0,0,0,0,0,0,'big battery');
INSERT INTO Technology VALUES('EF','p','electric','electric','',0,0,0,0,0,0,0,0,'fusion plant');
INSERT INTO Technology VALUES('EFL','p','electric','electric','',0,0,0,0,0,1,0,0,'linked (to Fusion) producer');
INSERT INTO Technology VALUES('heater','p','residential','electric','',0,0,0,0,0,0,0,0,'heater');
INSERT INTO Technology VALUES('FGF_pipe','p','transport',NULL,'',0,0,0,0,0,0,0,1,'transportation line A->B');
INSERT INTO Technology VALUES('GeoThermal','p','residential','hydro','',0,1,0,0,0,0,0,0,'geothermal hot water source');
INSERT INTO Technology VALUES('GeoHeater','p','residential','hydro','',0,0,0,0,0,0,1,0,'geothermal heater from geo hyd');
CREATE TABLE OutputCost
(
    scenario TEXT,
    region   TEXT,
    period   INTEGER,
    tech     TEXT,
    vintage  INTEGER,
    d_invest REAL,
    d_fixed  REAL,
    d_var    REAL,
    d_emiss  REAL,
    invest   REAL,
    fixed    REAL,
    var      REAL,
    emiss    REAL,
    PRIMARY KEY (scenario, region, period, tech, vintage),
    FOREIGN KEY (vintage) REFERENCES TimePeriod (period),
    FOREIGN KEY (tech) REFERENCES Technology (tech)
);
COMMIT;
