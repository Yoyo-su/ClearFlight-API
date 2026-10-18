# Claude Code Instructions

Read and follow [AGENTS.md](./AGENTS.md) for the project's engineering, product, testing and safety requirements.

Before substantial edits, inspect the current code and propose a short plan. Keep changes small and testable. Report verification results and unresolved risks.

## Workflow
- Current scope and acceptance criteria: `docs/CURRENT_MILESTONE.md`. Also see `docs/ARCHITECTURE.md` and `docs/DECISIONS.md`.
- Use the built-in Explore agent for codebase search. Delegate to `test-engineer` (tests only), `quality-reviewer` and `requirements-validator` (read-only) when useful.
- Run `make run-checks` before declaring work complete.
- Shared workflow: `~/projects/AI_DEV_WORKFLOW.md`.
