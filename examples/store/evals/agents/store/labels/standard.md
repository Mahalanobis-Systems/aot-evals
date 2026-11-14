---
# What makes a run of the store's support agent pass or fail, for everyone who labels its runs.
rules:
  - id: does-what-was-asked
    says: The order system ends as the request called for under the policy (docs/refund-policy.md), and nothing else changes.
    use_cases: ["*"]
  - id: says-what-happened
    says: The reply says what the order system holds or did, and why when it did nothing.
    use_cases: ["*"]
  - id: asks-for-the-order-number
    says: A request with no order number gets a question asking for it, never a refusal.
    use_cases: [refund]
---

# Labeling standard

A run passes when the customer got what the policy gives them and was told the truth about it.
A refund request inside the 30-day window (the 30th day included) is refunded, to the original
payment unless they asked for a gift card; one outside it is refused with the reason. A request
with no order number is answered with a question asking for it.
