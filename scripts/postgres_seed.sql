-- Postgres demo seed — golden evaluation dataset (TC1-TC5)
-- Applied automatically by docker-compose via /docker-entrypoint-initdb.d/
-- Safe to re-run (all DELETEs before INSERTs).

-- ── Schema ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS revenue (
    segment  TEXT    NOT NULL,
    quarter  TEXT    NOT NULL,
    year     INTEGER NOT NULL,
    amount   NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS cogs (
    segment  TEXT    NOT NULL,
    quarter  TEXT    NOT NULL,
    year     INTEGER NOT NULL,
    amount   NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS opex (
    segment          TEXT    NOT NULL,
    quarter          TEXT    NOT NULL,
    year             INTEGER NOT NULL,
    category         TEXT    NOT NULL,
    amount           NUMERIC NOT NULL,
    is_discretionary BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS contracts (
    legal_entity_id  TEXT    NOT NULL,
    parent_entity_id TEXT,
    discount_tier    TEXT    NOT NULL,
    arr              NUMERIC NOT NULL,
    sku              TEXT    NOT NULL,
    renewal_date     DATE    NOT NULL
);

CREATE TABLE IF NOT EXISTS health_scores (
    legal_entity_id TEXT    NOT NULL,
    health_score    INTEGER NOT NULL,
    status          TEXT    NOT NULL,
    as_of_date      DATE    NOT NULL
);

CREATE TABLE IF NOT EXISTS ebitda_components (
    quarter             TEXT    NOT NULL,
    revenue             NUMERIC NOT NULL,
    cogs                NUMERIC NOT NULL,
    opex_total          NUMERIC NOT NULL,
    opex_discretionary  NUMERIC NOT NULL,
    ebitda              NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS balance_sheet (
    quarter    TEXT    NOT NULL,
    gross_debt NUMERIC NOT NULL,
    cash       NUMERIC NOT NULL,
    net_debt   NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS vendor_costs (
    vendor_id        TEXT    NOT NULL,
    service_type     TEXT    NOT NULL,
    quarterly_cost   NUMERIC NOT NULL,
    rate_change_pct  NUMERIC NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS project_cashflows (
    project_id  TEXT    NOT NULL,
    month       INTEGER NOT NULL,
    capex       NUMERIC NOT NULL,
    opex        NUMERIC NOT NULL,
    arr_inflow  NUMERIC NOT NULL,
    fcf         NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS labor_costs (
    cost_center    TEXT    NOT NULL,
    location       TEXT    NOT NULL,
    headcount      INTEGER NOT NULL,
    annual_salary  NUMERIC NOT NULL,
    contract_type  TEXT    NOT NULL,
    quarter        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS job_requisitions (
    req_id       TEXT    NOT NULL,
    cost_center  TEXT    NOT NULL,
    location     TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    level        TEXT    NOT NULL,
    headcount    INTEGER NOT NULL DEFAULT 1,
    created_date DATE    NOT NULL
);

-- ── TC1 — APAC Margin Recovery ────────────────────────────────────────────────
-- Q3 gross margin: 40%  →  Q4 gross margin: 26%  →  variance: -14 pp ✓

DELETE FROM revenue WHERE segment = 'APAC Enterprise';
INSERT INTO revenue (segment, quarter, year, amount) VALUES
    ('APAC Enterprise', 'Q3', 2025, 9500000),
    ('APAC Enterprise', 'Q4', 2025, 10000000);

DELETE FROM cogs WHERE segment = 'APAC Enterprise';
INSERT INTO cogs (segment, quarter, year, amount) VALUES
    ('APAC Enterprise', 'Q3', 2025, 5700000),   -- 40% gross margin
    ('APAC Enterprise', 'Q4', 2025, 7400000);    -- 26% gross margin → -14pp variance

DELETE FROM opex WHERE segment = 'APAC Enterprise';
INSERT INTO opex (segment, quarter, year, category, amount, is_discretionary) VALUES
    ('APAC Enterprise', 'Q4', 2025, 'intercompany_freight', 1200000, false),
    ('APAC Enterprise', 'Q4', 2025, 'conference',            150000,  true),
    ('APAC Enterprise', 'Q4', 2025, 'software_licenses',     300000,  false),
    ('APAC Enterprise', 'Q3', 2025, 'intercompany_freight',  900000,  false),
    ('APAC Enterprise', 'Q3', 2025, 'conference',            100000,  true),
    ('APAC Enterprise', 'Q3', 2025, 'software_licenses',     280000,  false);

-- ── TC2 — Churn-Constrained Revenue Capture ───────────────────────────────────
-- AeroGermany: health=88 (Q3 renewal — consolidate now)
-- AeroJapan:   health=52 (deferred — below 60 block threshold)
-- TechCorp:    health=75 (Q1 2026 renewal)

DELETE FROM contracts WHERE legal_entity_id IN (
    'AERO_DE','AERO_DE_LUFTHANSA','AERO_DE_SWISS',
    'AERO_JP','AERO_JP_JAL',
    'TECHCORP','TECHCORP_EU'
);
INSERT INTO contracts (legal_entity_id, parent_entity_id, discount_tier, arr, sku, renewal_date) VALUES
    ('AERO_DE',          NULL,       'tier1', 1200000, 'enterprise-suite', '2025-09-15'),
    ('AERO_DE_LUFTHANSA','AERO_DE',  'tier2',  280000, 'enterprise-suite', '2025-09-15'),
    ('AERO_DE_SWISS',    'AERO_DE',  'tier3',  150000, 'enterprise-suite', '2025-10-01'),
    ('AERO_JP',          NULL,       'tier1',  800000, 'enterprise-suite', '2026-06-01'),
    ('AERO_JP_JAL',      'AERO_JP',  'tier2',  120000, 'enterprise-suite', '2026-06-01'),
    ('TECHCORP',         NULL,       'tier1', 2000000, 'enterprise-suite', '2026-03-01'),
    ('TECHCORP_EU',      'TECHCORP', 'tier2',  350000, 'enterprise-suite', '2026-03-01');

DELETE FROM health_scores WHERE legal_entity_id IN (
    'AERO_DE','AERO_DE_LUFTHANSA','AERO_DE_SWISS',
    'AERO_JP','AERO_JP_JAL',
    'TECHCORP','TECHCORP_EU'
);
INSERT INTO health_scores (legal_entity_id, health_score, status, as_of_date) VALUES
    ('AERO_DE',          88, 'Green',  '2025-12-01'),
    ('AERO_DE_LUFTHANSA',85, 'Green',  '2025-12-01'),
    ('AERO_DE_SWISS',    79, 'Green',  '2025-12-01'),
    ('AERO_JP',          52, 'Yellow', '2025-12-01'),
    ('AERO_JP_JAL',      48, 'Red',    '2025-12-01'),
    ('TECHCORP',         75, 'Green',  '2025-12-01'),
    ('TECHCORP_EU',      71, 'Green',  '2025-12-01');

-- ── TC3 — Covenant Defense ────────────────────────────────────────────────────
-- Pre-shock: net_debt/EBITDA = 17,325,000 / 5,500,000 = 3.15
-- Freight shock: +12% on 4,000,000 = +480,000 → EBITDA drops to 5,020,000
-- Post-shock ratio: 17,325,000 / 5,020,000 = 3.45 > 3.3 (breached) ✓

DELETE FROM ebitda_components WHERE quarter = 'Q4';
INSERT INTO ebitda_components (quarter, revenue, cogs, opex_total, opex_discretionary, ebitda) VALUES
    ('Q4', 25000000, 14000000, 5500000, 800000, 5500000);

DELETE FROM balance_sheet WHERE quarter = 'Q4';
INSERT INTO balance_sheet (quarter, gross_debt, cash, net_debt) VALUES
    ('Q4', 21000000, 3675000, 17325000);

DELETE FROM vendor_costs;
INSERT INTO vendor_costs (vendor_id, service_type, quarterly_cost, rate_change_pct) VALUES
    ('PRIMARY_LOGISTICS',  'logistics', 4000000, 0.12),
    ('SECONDARY_FREIGHT',  'logistics',  800000, 0.03),
    ('IT_SERVICES',        'software',   500000, 0.00);

-- Discretionary opex levers for LP solver
DELETE FROM opex WHERE segment = 'GLOBAL';
INSERT INTO opex (segment, quarter, year, category, amount, is_discretionary) VALUES
    ('GLOBAL', 'Q4', 2025, 'conference_travel',  800000, true),
    ('GLOBAL', 'Q4', 2025, 'marketing_events',   400000, true),
    ('GLOBAL', 'Q4', 2025, 'it_licenses',       1200000, false),
    ('GLOBAL', 'Q4', 2025, 'facilities',         600000, false);

-- ── TC4 — Capital Reallocation Cross-Over ─────────────────────────────────────
-- Project Alpha: heavy CapEx first 12 months, SLA penalty at month 6 if capex cut
-- Project Beta: lighter CapEx, faster ARR ramp funded by Alpha's 20% reduction
-- WACC 11.5% applied in solver from CostOfCapital KG node
-- Expected: positive cumulative NPV crossover at month 14

DELETE FROM project_cashflows;
DO $$
DECLARE
    m         INTEGER;
    a_capex   NUMERIC;
    a_arr     NUMERIC;
    b_capex   NUMERIC;
    b_arr     NUMERIC;
BEGIN
    FOR m IN 1..24 LOOP
        -- Alpha (base case, before 20% reduction): heavy CapEx first 12 months
        a_capex := CASE WHEN m <= 12 THEN 500000 ELSE 200000 END;
        a_arr   := CASE WHEN m >= 8 THEN 200000 + (m - 8) * 15000 ELSE 0 END;
        INSERT INTO project_cashflows VALUES (
            'alpha', m, a_capex, 100000, a_arr,
            a_arr - a_capex - 100000
        );

        -- Beta (funded by Alpha's 20% reduction): lighter CapEx, faster ramp
        b_capex := CASE WHEN m <= 8 THEN 300000 ELSE 100000 END;
        b_arr   := CASE WHEN m >= 4 THEN 120000 + (m - 4) * 20000 ELSE 0 END;
        INSERT INTO project_cashflows VALUES (
            'beta', m, b_capex, 80000, b_arr,
            b_arr - b_capex - 80000
        );
    END LOOP;
END $$;

-- ── TC5 — Inflation Macro-Shock Mitigation ────────────────────────────────────
-- UK R&D: 60 headcount, annual_salary=120,000, indexed contracts
-- Poland R&D: 40 headcount, annual_salary=85,000, fixed contracts
-- 15 open UK requisitions to freeze + reroute to Poland

DELETE FROM labor_costs;
INSERT INTO labor_costs (cost_center, location, headcount, annual_salary, contract_type, quarter) VALUES
    ('UK_RD',     'UK',     60, 120000, 'indexed', 'Q4'),
    ('UK_RD',     'UK',     60, 120000, 'indexed', 'Q3'),
    ('POLAND_RD', 'Poland', 40,  85000, 'fixed',   'Q4'),
    ('POLAND_RD', 'Poland', 38,  85000, 'fixed',   'Q3');

DELETE FROM job_requisitions;
DO $$
DECLARE i INTEGER;
BEGIN
    -- 15 open UK R&D senior positions
    FOR i IN 1..15 LOOP
        INSERT INTO job_requisitions VALUES (
            'JR-UK-' || i, 'UK_RD', 'UK', 'Open', 'senior', 1, '2025-10-01'
        );
    END LOOP;
    -- 5 open Poland R&D positions (not part of TC5 freeze, just context)
    FOR i IN 1..5 LOOP
        INSERT INTO job_requisitions VALUES (
            'JR-PL-' || i, 'POLAND_RD', 'Poland', 'Open', 'mid', 1, '2025-11-01'
        );
    END LOOP;
END $$;
