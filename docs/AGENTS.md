<!-- Parent: ../AGENTS.md -->

# AGENTS.md — docs/

Generated: 2026-04-08

## Purpose

Architecture documentation, data source registry, improvement backlog, and business planning documents for the DragonQuant data intelligence layer.

## Document Index

| File | Contents |
|------|---------|
| `architecture.md` | Detailed system architecture, data flow diagrams, module dependencies |
| `platform-architecture.md` | Full DragonQuant platform design, PSST signal mapping, backtest results |
| `data-sources.md` | Complete data source catalog, API key setup guide, source status |
| `continuous-improvement-priority.md` | Improvement backlog with priorities |
| `refactoring-plan-base-collector.md` | Base collector refactor plan and migration guide |
| `trading-journal-improvements.md` | Trading journal feature roadmap |
| `business-plan/` | Business planning documents |

## For AI Agents

### When to Read These Files

- Before any architectural change: read `architecture.md` and `platform-architecture.md`.
- Before adding a new data source: read `data-sources.md` to check existing coverage and API key requirements.
- Before modifying the base collector or common modules: read `refactoring-plan-base-collector.md`.
- Before planning new features: read `continuous-improvement-priority.md` to avoid duplicating in-progress work.

### Document Update Rules

- Update `data-sources.md` whenever a new collector or data source is added.
- Update `architecture.md` when module structure, data flow, or inter-repo contracts change.
- Do not modify `business-plan/` documents without explicit user instruction.
- Keep diagrams and tables consistent with the actual codebase state — stale docs are worse than no docs.

### Cross-Repo Contract

The `_posts/*.md` schema documented in `platform-architecture.md` is consumed by the `crypto` repository's `StructuredPostParser`. Any front matter schema change must be coordinated with that repository before merging.
