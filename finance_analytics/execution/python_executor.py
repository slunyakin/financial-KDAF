"""Async subprocess executor for LLM-generated solver code.

Per ADR-004: subprocess isolation chosen over RestrictedPython (in-process)
because a breakout is contained to a dead child process rather than the entire
FastAPI server. Import allowlist and data injection contract are defense in depth.

Data provenance contract (enforced before subprocess launch):
  Solver code MUST reference 'cypher_context' or 'sql_rows'. Hardcoding
  financial parameters (e.g. `revenue = 1200000`) is a silent correctness
  failure — the LLM would fabricate values instead of reading from the KG
  and SQL results. The Validator also checks variable usage after execution.

All 5 golden test cases require this executor:
  TC1: LP optimizer (elasticity, guardrail from cypher_context)
  TC2: sequencing algorithm (HealthIndex from cypher_context, ARR from sql_rows)
  TC3: LP solver (covenant, DPO lever from cypher_context)
  TC4: DCF loop (WACC, ForecastModel from cypher_context)
  TC5: delta engine (LaborRate, RampPenalty from cypher_context)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from finance_analytics.schemas.agent_outputs import PythonExecutorOutput

_HARNESS = Path(__file__).parent / "_sandbox_harness.py"
_DEFAULT_TIMEOUT_S: float = 30.0


def _uses_injected_vars(code: str) -> bool:
    """True if code references cypher_context or sql_rows (data provenance check)."""
    return "cypher_context" in code or "sql_rows" in code


async def execute_solver(
    code: str,
    cypher_context: Any,
    sql_rows: list,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> PythonExecutorOutput:
    """Execute solver code in an isolated subprocess.

    Raises:
        ValueError: code does not reference cypher_context or sql_rows
        TimeoutError: subprocess exceeds timeout
        RuntimeError: subprocess exits non-zero
    """
    if not _uses_injected_vars(code):
        raise ValueError(
            "Solver code must reference 'cypher_context' or 'sql_rows'. "
            "Hardcoding financial parameters is a provenance violation."
        )

    payload = json.dumps({
        "code": code,
        "cypher_context": cypher_context,
        "sql_rows": sql_rows,
    })

    start_ms = int(time.monotonic() * 1000)

    # Strip PYTHONPATH so the sandbox cannot reach the host application packages
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(_HARNESS),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=payload.encode()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"Solver exceeded {timeout:.0f}s time limit")

    execution_ms = int(time.monotonic() * 1000) - start_ms

    if proc.returncode != 0:
        raw_err = stderr_bytes.decode(errors="replace")
        try:
            err_data = json.loads(raw_err)
            msg = f"{err_data.get('type', 'Error')}: {err_data.get('error', raw_err)}"
        except json.JSONDecodeError:
            msg = raw_err or "Unknown solver error"
        raise RuntimeError(f"Solver subprocess failed — {msg}")

    output = json.loads(stdout_bytes.decode())
    return PythonExecutorOutput(
        code=code,
        result=output.get("result"),
        stdout=output.get("stdout", ""),
        execution_ms=execution_ms,
    )
