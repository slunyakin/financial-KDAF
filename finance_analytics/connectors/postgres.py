"""Postgres demo connector — asyncpg-backed DataLakeConnector for the golden dataset.

This connector is the DEMO/DEV FIXTURE only. It runs the 5 golden test cases
end-to-end without requiring a real customer data source.

In production, each customer brings their own data source connector
(connectors/snowflake.py, connectors/bigquery.py, etc.). The DATA_LAKE_ENGINE
env var selects the active connector at startup.

Pool sizing: max_size=50 supports ~20 concurrent users (50 conn / 2-3 queries avg).
This is acceptable for TC evaluation; not a production constraint.
"""
from __future__ import annotations

import time
from typing import Optional

import asyncpg

from finance_analytics.connectors.base import DataLakeConnector
from finance_analytics.schemas.agent_outputs import SQLQueryOutput

# Schema description for the golden dataset tables.
# Injected into the Text-to-SQL agent's system prompt via schema_description().
_DEMO_SCHEMA = """\
## Available tables (Postgres demo — golden evaluation dataset)

### revenue
| column   | type    | description               |
|----------|---------|---------------------------|
| segment  | text    | Business segment name     |
| quarter  | text    | e.g. 'Q4'                 |
| year     | integer |                           |
| amount   | numeric | Revenue amount            |

### cogs
| column   | type    | description               |
|----------|---------|---------------------------|
| segment  | text    |                           |
| quarter  | text    |                           |
| year     | integer |                           |
| amount   | numeric | Cost of goods sold        |

### opex
| column           | type    | description                      |
|------------------|---------|----------------------------------|
| segment          | text    |                                  |
| quarter          | text    |                                  |
| year             | integer |                                  |
| category         | text    | e.g. 'conference', 'travel'      |
| amount           | numeric |                                  |
| is_discretionary | boolean | True = cuttable without SLA risk |

### contracts
| column           | type    | description                       |
|------------------|---------|-----------------------------------|
| legal_entity_id  | text    |                                   |
| parent_entity_id | text    | NULL for top-level entities       |
| discount_tier    | text    | e.g. 'tier1', 'tier2'            |
| arr              | numeric | Annual recurring revenue          |
| sku              | text    | Product SKU                       |
| renewal_date     | date    |                                   |

### health_scores
| column          | type    | description                        |
|-----------------|---------|------------------------------------|
| legal_entity_id | text    |                                    |
| health_score    | integer | 0-100; <60 = churn risk            |
| status          | text    | 'Green' / 'Yellow' / 'Red'        |
| as_of_date      | date    |                                    |

### ebitda_components
| column              | type    | description           |
|---------------------|---------|-----------------------|
| quarter             | text    |                       |
| revenue             | numeric |                       |
| cogs                | numeric |                       |
| opex_total          | numeric |                       |
| opex_discretionary  | numeric |                       |
| ebitda              | numeric |                       |

### balance_sheet
| column     | type    | description            |
|------------|---------|------------------------|
| quarter    | text    |                        |
| gross_debt | numeric |                        |
| cash       | numeric |                        |
| net_debt   | numeric | gross_debt - cash      |

### vendor_costs
| column            | type    | description                    |
|-------------------|---------|--------------------------------|
| vendor_id         | text    |                                |
| service_type      | text    | e.g. 'logistics'               |
| quarterly_cost    | numeric |                                |
| rate_change_pct   | numeric | Proposed rate change (0.12 = +12%) |

### project_cashflows
| column      | type    | description              |
|-------------|---------|--------------------------|
| project_id  | text    | e.g. 'alpha', 'beta'     |
| month       | integer | 1-24                     |
| capex       | numeric |                          |
| opex        | numeric |                          |
| arr_inflow  | numeric |                          |
| fcf         | numeric | Free cash flow           |

### labor_costs
| column        | type    | description                          |
|---------------|---------|--------------------------------------|
| cost_center   | text    |                                      |
| location      | text    | e.g. 'UK', 'Poland'                 |
| headcount     | integer |                                      |
| annual_salary | numeric |                                      |
| contract_type | text    | 'indexed' / 'fixed'                  |
| quarter       | text    |                                      |

### job_requisitions
| column      | type    | description                          |
|-------------|---------|--------------------------------------|
| req_id      | text    |                                      |
| cost_center | text    |                                      |
| location    | text    |                                      |
| status      | text    | 'Open' / 'Filled'                   |
| level       | text    | e.g. 'senior', 'mid'                |
| headcount   | integer |                                      |
| created_date| date    |                                      |
"""


class PostgresConnector(DataLakeConnector):
    """Demo Postgres connector backed by asyncpg connection pool."""

    dialect = "postgresql"

    def __init__(self, dsn: str, max_pool_size: int = 50) -> None:
        self._dsn = dsn
        self._max_pool_size = max_pool_size
        self._pool: Optional[asyncpg.Pool] = None

    async def init_pool(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=5,
            max_size=self._max_pool_size,
        )

    async def execute(self, query: str, params: dict | None = None) -> SQLQueryOutput:
        if self._pool is None:
            raise RuntimeError("PostgresConnector pool not initialized — call init_pool()")
        start_ms = int(time.monotonic() * 1000)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
        execution_ms = int(time.monotonic() * 1000) - start_ms
        row_dicts = [dict(row) for row in rows]
        return SQLQueryOutput(
            sql=query,
            rows=row_dicts,
            row_count=len(row_dicts),
            execution_ms=execution_ms,
        )

    async def schema_description(self) -> str:
        return _DEMO_SCHEMA

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
