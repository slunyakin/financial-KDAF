# ADR-003: LangGraph StateGraph for Agent Orchestration

**Status:** Accepted
**Date:** 2026-06-02

## Context

The system requires a multi-agent chain with conditional routing (cache hit → early exit), retry cycles (Validator failure → back to Refiner with context), and a sequential execution dependency (Cypher context must be available before SQL generation). The orchestration framework must run locally in Docker Compose without cloud credentials.

Previous consideration: AWS Strands. Rejected — requires AWS credentials for local development, making Docker Compose dev environment impractical.

## Decision

Use **LangChain + LangGraph `StateGraph`** for all agent orchestration.

**Agent chain (sequential — not parallel):**
```
Supervisor → check Redis cache → hit: return cached answer
           → Refiner (sets requires_solver, domain_terms, max_retries)
           → Text-to-Cypher (fetch BusinessRules/KnownAnomalies → AgentState.cypher_context)
           → Text-to-SQL (reads cypher_context from AgentState; injects KG context into prompt)
           → PythonExecutor (subprocess sandbox; only if requires_solver=True)
           → Validator → Reflection → Cache Write → Response
           (on Validator failure + retry_count < max_retries: back to Refiner with context_notes)
           (on retry exhaustion: Reflection(confidence_score=0.0) + EnrichmentTask write)
```

Text-to-Cypher runs before Text-to-SQL (sequential, not parallel) so that KG context is available in the SQL generation prompt. Parallel execution would cause SQL to generate without business rule context, producing wrong answers on all 5 golden test cases.

**AgentState** is defined in `finance_analytics/schemas/agent_state.py` and must be written before any agent node code.

## Consequences

- Runs fully locally in Docker Compose; no AWS credentials required
- Sequential Cypher→SQL costs ~200–400ms vs. a hypothetical parallel execution
- This latency is acceptable within the 5–30s deep-thinking SLA and is required for correctness on TC1/TC3/TC5 (all require KG context injected into SQL prompt)
- LangGraph StateGraph cycle (Validator→Refiner retry) is natively supported
