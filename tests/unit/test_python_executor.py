"""Unit tests for the PythonExecutor data provenance check.

The subprocess execution itself requires a running Python interpreter and
is tested in tests/integration/. These unit tests cover the synchronous
validation logic that runs before the subprocess is launched.
"""
import pytest

from finance_analytics.execution.python_executor import _uses_injected_vars


class TestUsesInjectedVars:
    def test_references_cypher_context(self) -> None:
        code = "coefficient = cypher_context['elasticity']['coefficient']\nresult = coefficient * 0.04"
        assert _uses_injected_vars(code) is True

    def test_references_sql_rows(self) -> None:
        code = "total = sum(r['amount'] for r in sql_rows)\nresult = total"
        assert _uses_injected_vars(code) is True

    def test_references_both(self) -> None:
        code = "wacc = cypher_context['wacc']\nflows = [r['fcf'] for r in sql_rows]\nresult = sum(flows)"
        assert _uses_injected_vars(code) is True

    def test_hardcoded_only_fails(self) -> None:
        # LLM fabricated parameters — provenance violation
        code = "revenue = 1200000\nebitda = 340000\nresult = ebitda / revenue"
        assert _uses_injected_vars(code) is False

    def test_empty_code_fails(self) -> None:
        assert _uses_injected_vars("") is False


class TestExecuteSolverProvenance:
    """Verify ValueError is raised before subprocess launch when code lacks injected vars."""

    @pytest.mark.asyncio
    async def test_raises_on_hardcoded_params(self) -> None:
        from finance_analytics.execution.python_executor import execute_solver

        with pytest.raises(ValueError, match="provenance"):
            await execute_solver(
                code="result = 4.1",   # no cypher_context or sql_rows reference
                cypher_context={},
                sql_rows=[],
            )
