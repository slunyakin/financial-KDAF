// Neo4j demo seed — golden evaluation dataset (TC1-TC5)
// Applied manually or via scripts/smoke_test.sh against localhost:7687
// Safe to re-run (MERGE is idempotent; SET overwrites properties).

// ── Schema — indexes and constraints ────────────────────────────────────────
// Required for query-history performance: GET /api/v1/history filters by user_id
CREATE INDEX question_user_id IF NOT EXISTS FOR (q:Question) ON (q.user_id);
// Deduplicates write_question_node on client retries within the cache TTL window
CREATE CONSTRAINT question_id IF NOT EXISTS FOR (q:Question) REQUIRE q.id IS UNIQUE;

// ── TC1 — APAC Margin Recovery ──────────────────────────────────────────────

MERGE (seg_apac:Segment {id: 'APAC_ENTERPRISE'})
SET seg_apac.name = 'APAC Enterprise',
    seg_apac.description = 'Asia-Pacific enterprise segment',
    seg_apac.visibility = ['analyst', 'finance', 'executive'];

MERGE (el:Elasticity {id: 'ELAST_APAC_PRICE'})
SET el.segment_id = 'APAC_ENTERPRISE',
    el.price_elasticity = -0.8,
    el.description = 'Price elasticity of demand for APAC Enterprise: -0.8',
    el.visibility = ['analyst', 'finance'];

MERGE (gr_vol:Guardrail {id: 'GUARD_APAC_VOLUME'})
SET gr_vol.segment_id = 'APAC_ENTERPRISE',
    gr_vol.metric = 'volume_impact_pct',
    gr_vol.max_absolute_value = 0.05,
    gr_vol.description = 'Maximum allowed volume loss from any price increase: 5%',
    gr_vol.visibility = ['analyst', 'finance', 'executive'];

MERGE (br_gm:BusinessRule {id: 'BR_APAC_GM_FLOOR'})
SET br_gm.name = 'APAC Gross Margin Floor',
    br_gm.description = 'APAC Enterprise gross margin must remain at or above 30% after any pricing action',
    br_gm.threshold = 0.30,
    br_gm.metric = 'gross_margin_pct',
    br_gm.segment_id = 'APAC_ENTERPRISE',
    br_gm.visibility = ['analyst', 'finance', 'executive'];

MERGE (br_freight:BusinessRule {id: 'BR_FREIGHT_NON_DISC'})
SET br_freight.name = 'Intercompany Freight Non-Discretionary',
    br_freight.description = 'Intercompany freight costs are non-discretionary and must be allocated at cost; no deferral permitted',
    br_freight.category = 'intercompany_freight',
    br_freight.is_discretionary = false,
    br_freight.visibility = ['analyst', 'finance'];

MERGE (ka_freight:KnownAnomaly {id: 'KA_Q4_2025_FREIGHT_SPIKE'})
SET ka_freight.name = 'Q4 2025 APAC Freight Spike',
    ka_freight.description = 'APAC Enterprise intercompany freight costs spiked +33% QoQ in Q4 2025 due to Asia logistics disruption; depressed gross margin by ~14pp vs Q3',
    ka_freight.quarter = 'Q4',
    ka_freight.year = 2025,
    ka_freight.segment_id = 'APAC_ENTERPRISE',
    ka_freight.category = 'intercompany_freight',
    ka_freight.impact_amount = 300000,
    ka_freight.visibility = ['analyst', 'finance'];

MERGE (seg_apac)-[:HAS_ELASTICITY]->(el);
MERGE (seg_apac)-[:GOVERNED_BY]->(gr_vol);
MERGE (seg_apac)-[:GOVERNED_BY]->(br_gm);
MERGE (seg_apac)-[:GOVERNED_BY]->(br_freight);
MERGE (seg_apac)-[:HAS_ANOMALY]->(ka_freight);

// ── TC2 — Churn-Constrained Revenue Capture ─────────────────────────────────

MERGE (le_aero_de:LegalEntity {id: 'AERO_DE'})
SET le_aero_de.name = 'AeroGermany',
    le_aero_de.country = 'Germany',
    le_aero_de.industry = 'Aerospace',
    le_aero_de.tier = 'tier1',
    le_aero_de.visibility = ['cs', 'sales', 'finance', 'executive'];

MERGE (le_lufthansa:LegalEntity {id: 'AERO_DE_LUFTHANSA'})
SET le_lufthansa.name = 'AeroGermany Lufthansa Subsidiary',
    le_lufthansa.country = 'Germany',
    le_lufthansa.industry = 'Aerospace',
    le_lufthansa.tier = 'tier2',
    le_lufthansa.visibility = ['cs', 'sales', 'finance'];

MERGE (le_swiss:LegalEntity {id: 'AERO_DE_SWISS'})
SET le_swiss.name = 'AeroGermany Swiss Subsidiary',
    le_swiss.country = 'Switzerland',
    le_swiss.industry = 'Aerospace',
    le_swiss.tier = 'tier3',
    le_swiss.visibility = ['cs', 'sales', 'finance'];

MERGE (le_aero_jp:LegalEntity {id: 'AERO_JP'})
SET le_aero_jp.name = 'AeroJapan',
    le_aero_jp.country = 'Japan',
    le_aero_jp.industry = 'Aerospace',
    le_aero_jp.tier = 'tier1',
    le_aero_jp.visibility = ['cs', 'sales', 'finance', 'executive'];

MERGE (le_jal:LegalEntity {id: 'AERO_JP_JAL'})
SET le_jal.name = 'AeroJapan JAL Subsidiary',
    le_jal.country = 'Japan',
    le_jal.industry = 'Aerospace',
    le_jal.tier = 'tier2',
    le_jal.visibility = ['cs', 'sales', 'finance'];

MERGE (le_techcorp:LegalEntity {id: 'TECHCORP'})
SET le_techcorp.name = 'TechCorp',
    le_techcorp.country = 'USA',
    le_techcorp.industry = 'Technology',
    le_techcorp.tier = 'tier1',
    le_techcorp.visibility = ['cs', 'sales', 'finance', 'executive'];

MERGE (le_techcorp_eu:LegalEntity {id: 'TECHCORP_EU'})
SET le_techcorp_eu.name = 'TechCorp EU',
    le_techcorp_eu.country = 'Netherlands',
    le_techcorp_eu.industry = 'Technology',
    le_techcorp_eu.tier = 'tier2',
    le_techcorp_eu.visibility = ['cs', 'sales', 'finance'];

MERGE (le_aero_de)-[:PARENT_OF]->(le_lufthansa);
MERGE (le_aero_de)-[:PARENT_OF]->(le_swiss);
MERGE (le_aero_jp)-[:PARENT_OF]->(le_jal);
MERGE (le_techcorp)-[:PARENT_OF]->(le_techcorp_eu);

MERGE (hi:HealthIndex {id: 'HI_CONSOLIDATION_THRESHOLD'})
SET hi.name = 'Consolidation Block Threshold',
    hi.min_score = 60,
    hi.description = 'Entities with health score below 60 are blocked from contract consolidation; must stabilize before any upsell action',
    hi.visibility = ['cs', 'sales', 'finance'];

MERGE (br_parent_first:BusinessRule {id: 'BR_CONSOLIDATE_PARENT_FIRST'})
SET br_parent_first.name = 'Consolidate Parent Before Subsidiaries',
    br_parent_first.description = 'Parent entity contract must be consolidated before any subsidiary entity consolidation can proceed; prevents orphaned subsidiary risk',
    br_parent_first.visibility = ['sales', 'finance', 'legal'];

MERGE (br_health_block:BusinessRule {id: 'BR_HEALTH_BLOCK'})
SET br_health_block.name = 'Health Score Consolidation Block',
    br_health_block.description = 'Any entity or subsidiary with health score < 60 is automatically deferred; consolidation opportunity is logged but not actioned',
    br_health_block.threshold = 60,
    br_health_block.metric = 'health_score',
    br_health_block.visibility = ['cs', 'sales', 'finance'];

MERGE (cal_q3:Calendar {id: 'CAL_Q3_2025_RENEWAL'})
SET cal_q3.name = 'Q3 2025 Renewal Window',
    cal_q3.start_date = '2025-07-01',
    cal_q3.end_date = '2025-09-30',
    cal_q3.description = 'Q3 2025 contract renewal and consolidation window',
    cal_q3.visibility = ['sales', 'cs', 'finance'];

MERGE (le_aero_de)-[:GOVERNED_BY]->(br_parent_first);
MERGE (le_aero_de)-[:GOVERNED_BY]->(br_health_block);
MERGE (hi)-[:APPLIES_TO]->(le_aero_de);
MERGE (hi)-[:APPLIES_TO]->(le_aero_jp);
MERGE (cal_q3)-[:COVERS]->(le_aero_de);

// ── TC3 — Covenant Defense ───────────────────────────────────────────────────

MERGE (cov:Covenant {id: 'COV_NET_DEBT_EBITDA'})
SET cov.name = 'Senior Credit Facility Net Debt / EBITDA Covenant',
    cov.threshold = 3.3,
    cov.metric = 'net_debt_to_ebitda',
    cov.breach_action = 'technical_default',
    cov.description = 'Net Debt / EBITDA must not exceed 3.3x per the senior credit agreement; breach triggers technical default and accelerated repayment clause',
    cov.visibility = ['finance', 'executive', 'legal'];

MERGE (vendor_primary:Vendor {id: 'PRIMARY_LOGISTICS'})
SET vendor_primary.name = 'Primary Logistics',
    vendor_primary.service_type = 'logistics',
    vendor_primary.description = 'Primary freight and logistics vendor; largest COGS-affecting vendor',
    vendor_primary.visibility = ['finance', 'procurement'];

MERGE (vendor_secondary:Vendor {id: 'SECONDARY_FREIGHT'})
SET vendor_secondary.name = 'Secondary Freight',
    vendor_secondary.service_type = 'logistics',
    vendor_secondary.description = 'Secondary freight vendor; partial fallback capacity',
    vendor_secondary.visibility = ['finance', 'procurement'];

MERGE (oe_conf:OperatingExpense {id: 'OE_CONFERENCE_TRAVEL'})
SET oe_conf.category = 'conference_travel',
    oe_conf.is_discretionary = true,
    oe_conf.quarter = 'Q4',
    oe_conf.description = 'Discretionary conference and travel expenses; can be cut without operational impact in quarter',
    oe_conf.visibility = ['finance'];

MERGE (oe_mkt:OperatingExpense {id: 'OE_MARKETING_EVENTS'})
SET oe_mkt.category = 'marketing_events',
    oe_mkt.is_discretionary = true,
    oe_mkt.quarter = 'Q4',
    oe_mkt.description = 'Discretionary marketing events spend; can be deferred to following quarter',
    oe_mkt.visibility = ['finance'];

MERGE (oe_it:OperatingExpense {id: 'OE_IT_LICENSES'})
SET oe_it.category = 'it_licenses',
    oe_it.is_discretionary = false,
    oe_it.quarter = 'Q4',
    oe_it.description = 'Non-discretionary IT license renewals; deferral would cause service disruption',
    oe_it.visibility = ['finance'];

MERGE (wc_dpo:WorkingCapital {id: 'WC_DPO_LEVER'})
SET wc_dpo.lever_type = 'DPO',
    wc_dpo.name = 'Days Payable Outstanding Extension',
    wc_dpo.current_dpo = 30,
    wc_dpo.target_dpo = 45,
    wc_dpo.release_amount = 1500000,
    wc_dpo.description = 'Extend DPO from 30 to 45 days releases approximately $1.5M in working capital; requires vendor renegotiation',
    wc_dpo.visibility = ['finance', 'treasury'];

MERGE (br_cov:BusinessRule {id: 'BR_COVENANT_HEADROOM'})
SET br_cov.name = 'Covenant Headroom Maintenance',
    br_cov.description = 'Net Debt / EBITDA must be maintained at or below 3.3x at all times; breach of this threshold triggers lender notification within 5 business days',
    br_cov.threshold = 3.3,
    br_cov.metric = 'net_debt_to_ebitda',
    br_cov.visibility = ['finance', 'executive', 'legal'];

MERGE (br_dpo:BusinessRule {id: 'BR_DPO_VENDOR_CONSENT'})
SET br_dpo.name = 'DPO Extension Requires Vendor Consent',
    br_dpo.description = 'DPO extension beyond 30 days requires written vendor consent; unilateral extension triggers penalty clauses in primary logistics contract',
    br_dpo.visibility = ['finance', 'legal', 'procurement'];

MERGE (cov)-[:GOVERNED_BY]->(br_cov);
MERGE (vendor_primary)-[:GOVERNED_BY]->(br_dpo);
MERGE (wc_dpo)-[:GOVERNED_BY]->(br_dpo);

// ── TC4 — Capital Reallocation Cross-Over ────────────────────────────────────

MERGE (proj_alpha:Project {id: 'PROJECT_ALPHA'})
SET proj_alpha.name = 'Project Alpha',
    proj_alpha.status = 'active',
    proj_alpha.description = 'Platform modernization — heavy CapEx in first 12 months; ARR ramp starts month 8; SLA penalty triggered at month 6 if CapEx cut below baseline',
    proj_alpha.arr_start_month = 8,
    proj_alpha.visibility = ['finance', 'executive', 'engineering'];

MERGE (proj_beta:Project {id: 'PROJECT_BETA'})
SET proj_beta.name = 'Project Beta',
    proj_beta.status = 'active',
    proj_beta.description = 'New product line — lighter CapEx; faster ARR ramp starting month 4; funded by 20% reduction from Alpha',
    proj_beta.arr_start_month = 4,
    proj_beta.visibility = ['finance', 'executive', 'engineering'];

MERGE (wacc:CostOfCapital {id: 'WACC_GLOBAL'})
SET wacc.name = 'Global WACC',
    wacc.rate = 0.115,
    wacc.description = 'Weighted average cost of capital: 11.5%; used for all NPV and DCF calculations',
    wacc.visibility = ['finance', 'executive'];

MERGE (cc_sla:ContractClause {id: 'CC_ALPHA_SLA_PENALTY'})
SET cc_sla.project_id = 'PROJECT_ALPHA',
    cc_sla.clause_type = 'SLA_PENALTY',
    cc_sla.trigger_month = 6,
    cc_sla.description = 'SLA penalty clause: if Alpha CapEx is reduced below baseline before month 6, a $500K penalty is triggered by the platform delivery contract',
    cc_sla.penalty_amount = 500000,
    cc_sla.visibility = ['finance', 'legal', 'executive'];

MERGE (fm_npv:ForecastModel {id: 'FM_NPV_CROSSOVER'})
SET fm_npv.model_type = 'DCF',
    fm_npv.expected_crossover_month_min = 10,
    fm_npv.expected_crossover_month_max = 18,
    fm_npv.description = 'Expected cumulative NPV crossover month when Beta is funded by 20% Alpha CapEx reduction; WACC from CostOfCapital node',
    fm_npv.wacc_node_id = 'WACC_GLOBAL',
    fm_npv.visibility = ['finance', 'executive'];

MERGE (br_cap_alloc:BusinessRule {id: 'BR_CAPITAL_REALLOCATION'})
SET br_cap_alloc.name = 'Capital Reallocation Policy',
    br_cap_alloc.description = 'CapEx reallocation between projects requires CFO approval; SLA penalty clauses must be evaluated before any reduction; NPV crossover must be positive within 24 months',
    br_cap_alloc.visibility = ['finance', 'executive', 'legal'];

MERGE (proj_alpha)-[:HAS_CONTRACT_CLAUSE]->(cc_sla);
MERGE (proj_alpha)-[:GOVERNED_BY]->(br_cap_alloc);
MERGE (proj_beta)-[:GOVERNED_BY]->(br_cap_alloc);
MERGE (fm_npv)-[:USES_RATE]->(wacc);
MERGE (proj_alpha)-[:MODELED_BY]->(fm_npv);
MERGE (proj_beta)-[:MODELED_BY]->(fm_npv);

// ── TC5 — Inflation Macro-Shock Mitigation ───────────────────────────────────

MERGE (mf_cpi:MacroFeed {id: 'MACRO_UK_CPI'})
SET mf_cpi.feed_type = 'CPI',
    mf_cpi.country = 'UK',
    mf_cpi.yoy_rate = 0.054,
    mf_cpi.as_of_quarter = 'Q4',
    mf_cpi.as_of_year = 2025,
    mf_cpi.description = 'UK CPI year-over-year rate: 5.4% as of Q4 2025; applied to all indexed-contract salary lines in UK cost centers',
    mf_cpi.visibility = ['finance', 'hr', 'executive'];

MERGE (lc_uk:LaborContract {id: 'LC_UK_RD_INDEXED'})
SET lc_uk.cost_center = 'UK_RD',
    lc_uk.location = 'UK',
    lc_uk.contract_type = 'indexed',
    lc_uk.index_source_id = 'MACRO_UK_CPI',
    lc_uk.description = 'UK R&D employment contracts indexed to UK CPI; annual salary adjustment applied automatically each January',
    lc_uk.visibility = ['finance', 'hr'];

MERGE (lc_pl:LaborContract {id: 'LC_POLAND_RD_FIXED'})
SET lc_pl.cost_center = 'POLAND_RD',
    lc_pl.location = 'Poland',
    lc_pl.contract_type = 'fixed',
    lc_pl.description = 'Poland R&D employment contracts are fixed-rate; no automatic CPI adjustment; renegotiated annually',
    lc_pl.visibility = ['finance', 'hr'];

MERGE (lr_uk:LaborRate {id: 'LR_UK_RD_SENIOR'})
SET lr_uk.location = 'UK',
    lr_uk.cost_center = 'UK_RD',
    lr_uk.level = 'senior',
    lr_uk.annual_salary = 120000,
    lr_uk.currency = 'GBP',
    lr_uk.headcount = 60,
    lr_uk.visibility = ['finance', 'hr'];

MERGE (lr_pl:LaborRate {id: 'LR_POLAND_RD_MID'})
SET lr_pl.location = 'Poland',
    lr_pl.cost_center = 'POLAND_RD',
    lr_pl.level = 'mid',
    lr_pl.annual_salary = 85000,
    lr_pl.currency = 'GBP',
    lr_pl.headcount = 40,
    lr_pl.visibility = ['finance', 'hr'];

MERGE (rp:RampPenalty {id: 'RP_UK_TO_POLAND_TRANSFER'})
SET rp.from_location = 'UK',
    rp.to_location = 'Poland',
    rp.ramp_months = 3,
    rp.productivity_loss_pct = 0.20,
    rp.quarterly_impact_bps = 65,
    rp.description = 'New Poland R&D hires replacing frozen UK requisitions operate at 80% productivity for first 3 months; net quarterly cost compression: ~65bps',
    rp.visibility = ['finance', 'hr'];

MERGE (jr_policy:JobRequisition {id: 'JR_FREEZE_POLICY'})
SET jr_policy.policy_name = 'Indexed Location Requisition Freeze',
    jr_policy.description = 'Open requisitions in CPI-indexed locations (UK) may be frozen and rerouted to fixed-contract locations (Poland) when macro shock exceeds 4% annualized; requires HR and finance co-approval',
    jr_policy.trigger_threshold = 0.04,
    jr_policy.visibility = ['finance', 'hr', 'executive'];

MERGE (br_freeze:BusinessRule {id: 'BR_HEADCOUNT_FREEZE_REROUTE'})
SET br_freeze.name = 'Headcount Freeze and Reroute Policy',
    br_freeze.description = 'When UK CPI exceeds 4% YoY, open UK R&D senior requisitions must be reviewed for freeze; frozen headcount may be rerouted to Poland R&D at fixed rates subject to RampPenalty assessment',
    br_freeze.trigger_metric = 'uk_cpi_yoy',
    br_freeze.trigger_threshold = 0.04,
    br_freeze.visibility = ['finance', 'hr', 'executive'];

MERGE (lc_uk)-[:INDEXED_TO]->(mf_cpi);
MERGE (lr_uk)-[:GOVERNED_BY]->(lc_uk);
MERGE (lr_pl)-[:GOVERNED_BY]->(lc_pl);
MERGE (rp)-[:FROM_RATE]->(lr_uk);
MERGE (rp)-[:TO_RATE]->(lr_pl);
MERGE (jr_policy)-[:GOVERNED_BY]->(br_freeze);
MERGE (mf_cpi)-[:TRIGGERS]->(br_freeze);

// ── Shared cross-TC relationships ────────────────────────────────────────────

// Covenant is a global constraint that can affect any segment
MERGE (seg_apac)-[:SUBJECT_TO]->(cov);

// CostOfCapital applies globally — link to covenant model
MERGE (wacc)-[:INFORMS]->(cov);

// ── KnownAnomaly nodes for TC2-TC5 ───────────────────────────────────────────
// TC1's KnownAnomaly (KA_Q4_2025_FREIGHT_SPIKE) is seeded above in the TC1 block.

MERGE (ka_aero_tier:KnownAnomaly {id: 'KA_AERO_GERMANY_TIER_MISMATCH'})
SET ka_aero_tier.name = 'AeroGermany Subsidiary Discount Tier Mismatch',
    ka_aero_tier.description = 'AeroGermany parent on tier1 while Lufthansa and Swiss subsidiaries remain on tier2/tier3; largest single-account ARR leakage source; consolidation window is Q3 renewal',
    ka_aero_tier.legal_entity_id = 'AERO_DE',
    ka_aero_tier.category = 'discount_tier_mismatch',
    ka_aero_tier.arr_leakage = 430000,
    ka_aero_tier.visibility = ['cs', 'sales', 'finance'];

MERGE (ka_freight_seasonal:KnownAnomaly {id: 'KA_Q4_FREIGHT_SEASONAL_SPIKE'})
SET ka_freight_seasonal.name = 'Q4 Freight Rate Seasonal Spike',
    ka_freight_seasonal.description = 'Primary logistics vendor historically increases rates 8-15% in Q4 due to seasonal demand; board precedent established in Q4 2024 for DPO extension as mitigant; 12% rate hike in current cycle is within historical range',
    ka_freight_seasonal.category = 'vendor_rate_increase',
    ka_freight_seasonal.vendor_id = 'PRIMARY_LOGISTICS',
    ka_freight_seasonal.quarter = 'Q4',
    ka_freight_seasonal.historical_range_min_pct = 0.08,
    ka_freight_seasonal.historical_range_max_pct = 0.15,
    ka_freight_seasonal.visibility = ['finance', 'procurement'];

MERGE (ka_alpha_sla:KnownAnomaly {id: 'KA_ALPHA_SLA_PENALTY_HISTORY'})
SET ka_alpha_sla.name = 'Project Alpha Month-6 SLA Penalty Historical Trigger',
    ka_alpha_sla.description = 'Project Alpha triggered the $500K SLA penalty clause at month 6 milestone in its prior engagement; root cause was CapEx reduction mid-project; high probability of recurrence if Alpha budget is cut again',
    ka_alpha_sla.project_id = 'PROJECT_ALPHA',
    ka_alpha_sla.category = 'sla_penalty_history',
    ka_alpha_sla.trigger_month = 6,
    ka_alpha_sla.prior_occurrence_count = 1,
    ka_alpha_sla.visibility = ['finance', 'legal', 'executive'];

MERGE (ka_uk_bonus:KnownAnomaly {id: 'KA_UK_RD_BONUS_CYCLE'})
SET ka_uk_bonus.name = 'UK R&D Q4 Bonus Cycle Inflation Overlap',
    ka_uk_bonus.description = 'UK R&D annual bonus accrual and CPI-indexed salary adjustment both fall in Q4; the two costs overlap and amplify the total Q4 labor expense impact; effect is ~25% higher than a naive quarterly-averaged model predicts',
    ka_uk_bonus.cost_center = 'UK_RD',
    ka_uk_bonus.category = 'labor_cost_seasonality',
    ka_uk_bonus.quarter = 'Q4',
    ka_uk_bonus.amplification_factor = 1.25,
    ka_uk_bonus.visibility = ['finance', 'hr'];

MERGE (le_aero_de)-[:HAS_ANOMALY]->(ka_aero_tier);
MERGE (vendor_primary)-[:HAS_ANOMALY]->(ka_freight_seasonal);
MERGE (proj_alpha)-[:HAS_ANOMALY]->(ka_alpha_sla);
MERGE (lc_uk)-[:HAS_ANOMALY]->(ka_uk_bonus);
