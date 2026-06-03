# ADR-004: Python Subprocess Sandbox for PythonExecutor

**Status:** Accepted
**Date:** 2026-06-02

## Context

All 5 golden test cases require mathematical solvers (LP optimizer, DCF loop, elasticity solver, sequencing algorithm, delta engine) that cannot be expressed in SQL. The system must execute LLM-generated Python code to produce these results.

LLM-generated code is untrusted and may contain malicious instructions. Two sandboxing approaches were evaluated:

1. **RestrictedPython** — in-process execution with AST transform to block dangerous builtins
2. **Subprocess with import allowlist + resource limits** — isolated child process; blocked at OS level

## Decision

Use **subprocess isolation** with:
- Import allowlist: `numpy`, `scipy`, `pandas` only. `subprocess`, `os`, `sys`, `socket` and all stdlib modules not on the allowlist are blocked.
- Resource limits applied to child process: CPU time cap, memory cap (via `resource` module on Linux; `ulimit` in Docker).
- Data injection contract: `cypher_context` and `sql_rows` are injected as named Python variables in the subprocess exec context. The LLM-generated solver reads from these variables — it cannot fabricate input data.
- Validator checks that generated code references `cypher_context` or `sql_rows` (not hardcoded literals for key parameters).

## Why Subprocess over RestrictedPython

Subprocess isolation limits blast radius to a dead child process if any escape occurs. RestrictedPython runs in-process — a breakout compromises the entire FastAPI server process and all user sessions.

## Consequences

- Generated solver code must read parameters from `cypher_context`/`sql_rows` variables — not hardcode them. Validator enforces this.
- Subprocess spawning adds ~20–50ms overhead per solver execution. Acceptable within 5–30s deep-thinking SLA.
- Security test must be run before v1 ships. Document results as an appendix to this ADR.
- Implementation: `execution/python_executor.py`
