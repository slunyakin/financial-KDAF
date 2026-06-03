"""
Subprocess sandbox harness for solver code execution.

This module is executed as __main__ in a child process by execution/python_executor.py.
It is NOT imported by the main application — do NOT add finance_analytics imports here.

Protocol:
  Stdin:  JSON {"code": str, "cypher_context": any, "sql_rows": list}
  Stdout: JSON {"result": any, "stdout": str}
  Stderr: JSON {"error": str, "type": str}  on failure
  Exit:   0 on success, 1 on error

Security layers applied here:
  1. Import allowlist enforced via builtins.__import__ hook before any user code runs
  2. Stdout captured so solver print() calls don't corrupt the JSON result channel
  3. Solver namespace pre-populated with cypher_context and sql_rows only
     (no access to host application objects)

Per ADR-004: subprocess isolation means a breakout is contained to this dead
child process, not the parent FastAPI server. Resource limits (CPU/memory) are
applied by the parent via asyncio timeout + Docker container limits.
"""
import builtins
import io
import json
import sys

_ALLOWED_IMPORTS: frozenset = frozenset(
    ["numpy", "scipy", "pandas", "math", "statistics", "json"]
)

_original_import = builtins.__import__


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    top_level = name.split(".")[0]
    if top_level not in _ALLOWED_IMPORTS:
        raise ImportError(
            f"Import of '{top_level}' is blocked in solver sandbox. "
            f"Allowed modules: {sorted(_ALLOWED_IMPORTS)}"
        )
    return _original_import(name, globals, locals, fromlist, level)


def main() -> None:
    # Install import guard before any user code can run
    builtins.__import__ = _guarded_import

    try:
        inputs = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        sys.stderr.write(json.dumps({"error": str(exc), "type": "InputError"}))
        sys.exit(1)

    cypher_context = inputs.get("cypher_context")
    sql_rows = inputs.get("sql_rows", [])
    code = inputs.get("code", "")

    # Capture solver stdout so it doesn't corrupt the result JSON channel
    captured_stdout = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured_stdout

    try:
        # cypher_context and sql_rows are injected as named variables.
        # Solver code MUST read parameters from these variables — not hardcode them.
        # The Validator checks variable usage before accepting the result.
        namespace = {"cypher_context": cypher_context, "sql_rows": sql_rows}
        exec(compile(code, "<solver>", "exec"), namespace)  # noqa: S102
        result = namespace.get("result")
    except Exception as exc:
        sys.stdout = real_stdout
        sys.stderr.write(json.dumps({"error": str(exc), "type": type(exc).__name__}))
        sys.exit(1)
    finally:
        sys.stdout = real_stdout

    sys.stdout.write(json.dumps({"result": result, "stdout": captured_stdout.getvalue()}))


if __name__ == "__main__":
    main()
