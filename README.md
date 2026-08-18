# financial-KDAF

**Status: archived predecessor.** This repository was the prototyping and research ground for [FPA-KDAF](https://github.com/slunyakin/FPA-KDAF), active from October 2025 through mid-2026. It has been superseded by FPA-KDAF, which is the actively maintained project. This repo is kept public for provenance — to preserve the design history, architecture decisions, and early implementation that led to FPA-KDAF.

**Do not build on this repository.** For current development, issues, and documentation, go to [FPA-KDAF](https://github.com/slunyakin/FPA-KDAF).

## What this was

financial-KDAF explored a knowledge-based finance analytics system: natural-language queries translated into SQL and Cypher, orchestrated across multiple specialized agents (Supervisor, Refiner, Text-to-Cypher, Text-to-SQL, Python solver, Validator, Reflection) against a Neo4j knowledge graph and a connector-agnostic data lake interface.

The architecture decisions made here — hybrid direct-driver/MCP routing, Neo4j as the knowledge graph source of truth, sequential Cypher-then-SQL execution, the Python subprocess sandbox — are recorded in `docs/adr/` and carried forward into FPA-KDAF.

## Provenance

- **Active:** October 2025 – mid-2026
- **Superseded by:** [FPA-KDAF](https://github.com/slunyakin/FPA-KDAF)
- **Kept for:** commit history, ADRs, and early implementation reference
