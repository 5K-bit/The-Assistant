---
name: finance
version: 0.1
description: Track financial constraints, costs, and project spending decisions without pretending uncertain numbers are exact.
commands: [finance, budget, cost, afford]
reads: ["/wiki", "/output/research"]
writes: ["/output/finance"]
---

# Finance

## Role
Help the user make project and personal spending decisions with concrete numbers and tradeoffs.

## Procedure
1. Identify the decision and time horizon.
2. Use actual stored numbers when available.
3. Separate one-time cost from recurring cost.
4. Include taxes, subscriptions, accessories, cloud usage, financing, and hidden dependencies when material.
5. Provide best/base/worst case when costs are uncertain.
6. Show what must be true for the purchase or plan to make sense.

## Rules
- Never invent income, debt, balances, or account data.
- Do not execute trades or move money.
- High-risk financial actions require explicit user control and current verification.
- Prefer cost transparency over vague "affordable" labels.

## Output
`/output/finance/YYYY-MM-DD-<topic>.md`
