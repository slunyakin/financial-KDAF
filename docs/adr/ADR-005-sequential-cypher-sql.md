# ADR-005: Sequential Cypher-then-SQL Execution

**Status:** Accepted
**Date:** 2026-06-02

## Context

The system's design doc originally described Text-to-Cypher and Text-to-SQL running in parallel (Phase 1). The engineering review identified a critical contradiction: the design also stated that "the context [Cypher] fetches is injected into the Text-to-SQL prompt." Parallel execution would mean SQL generates without business rule context.

This contradiction was escalated during engineering review (D3) and resolved before any code was written.

## Decision

**Text-to-Cypher runs before Text-to-SQL (sequential).** Cypher output is stored in `AgentState.cypher_context`. Text-to-SQL reads `cypher_context` from state and injects it into its system prompt.

## Why This Matters

All 5 golden test cases require KG context in the SQL prompt:
- TC1: elasticity coefficient and freight exclusion rule must be in SQL prompt for correct margin calculation
- TC3: covenant formula and DPO max-legal rule must be in SQL prompt for correct lever sizing
- TC5: CPI indexation formula must be in SQL prompt for correct UK labor cost escalation

Running in parallel produces wrong answers on these cases — the SQL agent generates with no business context.

## Consequences

- Sequential execution costs ~200–400ms vs. a hypothetical parallel run
- This is acceptable within the 5–30s deep-thinking SLA; correctness is non-negotiable in finance
- The agent chain module is named `chain_executor.py` (not `parallel_executor.py`) to reflect sequential execution
- Any future performance optimization that considers parallelizing these steps must re-run TC1/TC3/TC5 and verify KG context is still injected before SQL generation completes
