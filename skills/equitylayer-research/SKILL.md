---
name: equitylayer-research
description: Find, read and follow published EquityLayer Research Packs in Hermes, citing sources and never inventing figures. Says so plainly when none is published.
---

# EquityLayer published research

Use this when the user asks for EquityLayer's own published research. For the user's own thesis, use `equitylayer-thesis-harness`.

## Steps

1. Call `el_list_registry`. Use only the ids it returns.
2. **If it returns no entries, say that no Research Pack is published right now.** Do not use a retired pack as if it were current.
   Offer to track the user's own thesis instead (`el_plan_thesis`).
3. For a public pack, call `el_get_pack`, then `el_scorecard` with the same id. Do not try entries marked `locked`.
4. Show the result's `markdown`. It carries the source attribution and limits.
5. Offer `el_follow_create` so the user hears when new evidence arrives. `el_follow_list` shows local follows and
   `el_follow_check` checks them.

## Rules

- **Never invent numbers.** Quote figures only from a tool result and cite its source fields or `cite_as`.
- Keep reported facts, issuer notes and read-throughs apart. Say when a read-through is not human-reviewed.
- Say what the research does not establish: its `unknowns`, evidence limits and falsifier.
- Never say what to buy, sell, size or time. EquityLayer research is evidence, not a trade order, and not investment advice.

## Updates that need review

When `el_follow_check` returns `needs_review`, show the change. The stored card does not change until the user says to accept.
Only then call `el_follow_check` with `follow_id` and `accept_next: true`. Scheduled runs never accept.

## When access is refused

If a tool returns `entitlement_or_payment_required`, tell the user the entry is not on the free path and share `pricing_url`.
Never attempt payment or authentication for the user.
