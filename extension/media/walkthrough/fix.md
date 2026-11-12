# Fix it and review the evidence

Click the **CodeLens** above a finding (or the quick-fix bulb, or the button in the side bar). The panel shows the five steps live:

**Scanner → RAG → Our model → Checks → Human**

The model's fix only reaches you after it survived the checks: a safety guard, the project's **own tests**, a **real attack** against the running code, and a **re-scan**. The panel shows every attempt, every check and everything the model read.

- **Accept** applies the fix (with an **Undo** button). PatchAI never overwrites a file you edited in the meantime.
- **Reject** records your reason — the decision log is how the team learns.
