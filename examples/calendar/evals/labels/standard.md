---
# What makes a run of the toy calendar agent pass or fail. See the template `aot-evals init` writes
# for the general rules; this agent only books meetings, so two rules cover it.
rules:
  - id: writes-right
    says: The requested meeting exists exactly once, with the requested title, date and time.
    categories: [book-meeting]
  - id: leaves-the-rest
    says: Nothing on the calendar changes that the request didn't ask for.
    categories: ["*"]
---

# Labelling standard

A run passes when the calendar ends up exactly as the person asked: the meeting they asked for,
once, at the time they asked for, and nothing else touched. A message that needs no booking
passes only if the calendar is unchanged.
