---
name: equitylayer-research
description: Find, read, score and follow public EquityLayer research in Hermes, citing sources and never inventing figures.
---

# EquityLayer research workflow

Use this when the user wants EquityLayer research, or asks about a topic the Research Registry covers.

## Steps

1. Call `el_list_registry` to see what exists. Use the ids it returns.
2. Pick a **public** pack or view that fits the question. Do not try entries marked `locked`.
3. For a pack, call `el_get_pack`. For a view, call `el_test_thesis`. Then call `el_scorecard` with the same id.
4. Show the result's `markdown`. It already carries the source attribution and limits.
5. Offer `el_follow_create` so the user can come back when new evidence arrives. Use `thesis_id` for a view and `pack_id` for a pack.
6. Use `el_follow_list` to show local follows, and `el_follow_check` to check them.

## Rules

- **Never invent numbers.** Quote figures only from a tool result and cite that result's source fields or `cite_as`.
- Keep reported facts, issuer notes and read-throughs separate. Say when a read-through is not human-reviewed.
- Say what the research does not establish. Use its `unknowns`, evidence limits and falsifier.
- Monthly revenue is not proof of AI demand, margin, valuation or causality.
- Do not recommend buying or selling. EquityLayer research is evidence, not a trade order, and this is not investment advice.

## Updates that need review

When `el_follow_check` returns `needs_review`, show the change and read the new version with `el_get_pack`.
The stored card does not change until the user says to accept. Only then call `el_follow_check` with
`follow_id` and `accept_next: true`. Scheduled runs never accept.

## When access is refused

If a tool returns `entitlement_or_payment_required`, tell the user the entry is not on the free public path and share
`pricing_url`. Offer a public entry instead. Never attempt payment or authentication for the user.

## Scheduling

To check follows on a schedule, point the user to `/blueprint equitylayer:follow-check` or `/el schedule`.
