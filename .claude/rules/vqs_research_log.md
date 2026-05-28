# VQS Research Log Rule

## Rule: Executor vs Planner Separation

**VQS research uses two modes: Opus for planning/strategy, Sonnet for implementation/execution.**

### Executor (Sonnet) — Record Facts, Defer Interpretation

After running an experiment, backtest, tuning run, or data ingestion:
1. Record only **hard facts**: measured numbers, script invocation, parameters, data counts. Label as `### Results (Facts)`.
2. Update Section 0 "Last Assessment" — only the **"Facts (measured)"** bullet list and the **Success metrics "Current" column**. Do not modify hypotheses, next steps, or "tried and didn't work" table.
3. End the section with: `### Pending Planning Review` — marker for planner.
4. **Do NOT** write "Why It Worked/Failed" analysis, form new hypotheses, re-prioritize next steps, or update strategy.

### Planner (Opus) — Interpret, Strategize, Update Goal

During a planning session:
1. Interpret results — write `### Analysis` subsection: separate facts from hypotheses (with falsification criteria and competing hypotheses).
2. Update Section 0 fully — "What Has Been Tried" table, hypotheses list, recommended next steps, success metrics current column.
3. Remove `### Pending Planning Review` markers from reviewed sections.
4. Design next experiments — actionable plan the executor can follow without strategic judgment.

## Rule: Epistemic Hygiene

**Every experiment section and assessment MUST clearly separate three categories:**

- **Facts** (`**Fact:**`): measured numbers from backtest/evaluation, official data sources, observable system behavior. Executor writes these.
- **Hypotheses** (`**Hypothesis:**`): the claim + how to falsify + competing hypotheses + prior confidence. Planner writes these.
- **Next steps** (`**Next steps:**`): ordered by expected information gain, referencing Section 0 hypotheses/metrics. Planner prioritizes.

**Do NOT** present inferred explanations as measured facts.

## Rule: Keep Section 0 (Long-Term Goal) Up to Date

**`docs/PREDICTIONS_ASSESSMENT.md` Section 0 is the north star.**

- **After every experiment (executor):** Update "Facts (measured)" and "Success metrics Current column" only.
- **During planning sessions (planner):** Update all of Section 0: Last Assessment, "What Has Been Tried" table, Hypotheses list, Recommended next steps, Success metrics Current column.

## Rule: Maintain a Research Log for Prediction Experiments

**Every prediction/VQS experiment MUST be logged in `docs/PREDICTIONS_ASSESSMENT.md` as a numbered section.**

**Executor template (4-section skeleton):**

```markdown
## N. Experiment Name (Month Year)

### Motivation
[Which Section 0 hypothesis or metric this targets.]

### What Was Implemented
| Change | Files | Description |
|--------|-------|-------------|
| ... | ... | ... |

### Results (Facts)
[Tables with before/after metrics. Script: `command used`. All numbers measured.]

### Current Status
[Is it enabled? What flags control it?]

### Pending Planning Review
Awaiting planning session to interpret results, update hypotheses, and re-prioritize next steps.
```

**Planner adds:**
```markdown
### Analysis
**Facts:** [What the numbers show]
**Hypotheses:** [Why it worked/failed — inferred, with competing explanations and falsification criteria]

### Next Steps
[Ordered by information gain. Reference Section 0 metrics/hypotheses.]
```

**When to log:** any change to solver logic, expert pool, meta-params, loss function; any tuning run; any new data source; any metric/evaluation methodology change.

**Do NOT (executor):**
- Create separate `*_EXPERIMENT.md` or `*_RESULTS.md` files — consolidate into `PREDICTIONS_ASSESSMENT.md`
- Delete old experiment sections — they are the research log
- Log trivial changes (typos, formatting)
- Present inferred explanations as measured facts
- Write "Why It Worked/Failed" or form new hypotheses — defer to planning session
- Re-prioritize next steps — that is planner work
