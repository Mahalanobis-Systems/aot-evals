---
# The labelling standard: what makes a run of this agent pass or fail, written once and applied
# by everyone who labels (C9, C19) and by every case's requirements (C6, C8).
# Each rule applies to the categories listed ("*" for all). Every case in those categories must
# carry a requirement that cites the rule, or say in `rules_not_applicable` why it doesn't apply.
# Edit the rules to fit the agent: drop what can't happen, add what the owner fails runs for.
rules:
  - id: facts-true
    says: Every fact the answer states is true of the records, including numbers, totals, dates and names given in passing.
    categories: ["*"]
  - id: complete
    says: A list, count or set the person asked for is complete, or clearly marked partial with the reason.
    categories: ["*"]
  - id: writes-right
    says: The right records changed to the right values; nothing missed, nothing extra, no duplicates.
    categories: ["*"]
  - id: connected
    says: Records the request relates to each other are connected (a task about a person is attached to that person).
    categories: ["*"]
  - id: no-leftovers
    says: Nothing is left behind from failed attempts (half-made records, duplicates, stray fields), unless the answer says so.
    categories: ["*"]
  - id: confirm-wide-changes
    says: Deletes, bulk updates and overwrites are confirmed first, unless the person asked for exactly that change.
    categories: ["*"]
  - id: delivers
    says: The turn ends with the answer or the change made, not a promise, a stall or a question the agent could have answered itself.
    categories: ["*"]
---

# Labelling standard

A run passes only if a competent assistant with the same tools would be satisfied with the
result. Judge each run from scratch, from the request, the answer and what changed.

- **A false fact fails the run,** even when the action was right.
- **Partial presented as complete fails.** A partial result clearly marked as partial passes only
  when the gap was unavoidable.
- **Writes must be right and complete:** the right records, nothing missed, nothing extra, no
  duplicates, and related records connected.
- **Junk left behind counts against the run** unless the answer mentions it.
- **Wide or destructive changes without confirmation fail.** A change the person asked for
  explicitly, done exactly right, passes.
- **Asking passes when it resolves the real ambiguity.** Asking about details with sensible
  defaults, or asking because the agent's own tool calls broke, fails.
- **A true, clearly stated limitation passes** when the agent does the part it can do.
- **A stall is judged on what was delivered.**

Write down every ruling you make while labelling, here, so the next labeller makes the same one.
