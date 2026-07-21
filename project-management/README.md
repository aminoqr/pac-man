# Project Management

Evidence trail for the 42 Pac-Man defense (subject VIII–IX). This
directory documents *how* the project was run, not how the code works
(that is in the root `README.md`, `REFERENCE.md`, and the module
docstrings).

| Document | Contents |
|---|---|
| [timeline.md](timeline.md) | Milestone-by-milestone chronology |
| [progress-tracking.md](progress-tracking.md) | Status vs. plan (`../PLAN.md` is the live tracker) |
| [design-decisions.md](design-decisions.md) | Key choices and their rationale |
| [risk-analysis.md](risk-analysis.md) | Risks, likelihood/impact, mitigations |
| [acceptance-test-plan.md](acceptance-test-plan.md) | What "done" means and how it is verified |
| [blocking-points.md](blocking-points.md) | Obstacles hit and how they were resolved |

**Method.** Work proceeded milestone by milestone in the order set by
`../PLAN.md`, each milestone leaving the repository runnable and
lint-clean, gated by its own acceptance criteria and test suite before
the next began. The three design documents (`../PLAN.md`,
`../REFERENCE.md`, `../TESTING_PLAYBOOK.md`) were authored up front and
served as the spec to implement against.
