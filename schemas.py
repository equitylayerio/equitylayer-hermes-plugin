"""Tool schemas the Hermes model reads. Each tool name is declared in plugin.yaml."""

_NOT_ADVICE = "Results are research evidence, not investment advice."

_FORMAT = {
    "type": "string",
    "enum": ["markdown", "json"],
    "description": "markdown (default) returns a chat-ready summary. json returns the raw EquityLayer payload.",
}

EL_LIST_REGISTRY = {
    "name": "el_list_registry",
    "description": (
        "List published EquityLayer Research Packs with access, freshness and next check date. It may be empty: "
        "when no Pack is current, say so plainly and offer el_plan_thesis for the user's own thesis instead. "
        f"Entries marked locked are not on the free path. {_NOT_ADVICE}"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "publisher": {"type": "string", "description": "Optional publisher id to filter by."},
        },
    },
}

EL_GET_PACK = {
    "name": "el_get_pack",
    "description": (
        "Open one EquityLayer Research Pack by its registry id, for example tw-monthly-revenue. Returns "
        "records, source attribution, methodology, unknowns and falsifier. Quote figures only from this "
        f"result and cite its source. {_NOT_ADVICE}"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pack_id": {"type": "string", "description": "Pack id from el_list_registry."},
            "version": {"type": "string", "description": "Optional exact version. Never selects a fallback."},
            "symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional Taiwan company codes for tw-monthly-revenue, for example 2383.TW.",
            },
            "format": _FORMAT,
            "max_records": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "description": "Records shown in markdown. Default 10.",
            },
        },
        "required": ["pack_id"],
    },
}

EL_SCORECARD = {
    "name": "el_scorecard",
    "description": (
        "Get the research-quality scorecard for a registry entry: pre-registered claims and how they "
        "resolved, freshness, official-source share, corrections and hashed editions. It measures "
        "research quality and is not a recommendation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "A pack id or view thesis_id from el_list_registry."},
            "format": _FORMAT,
        },
        "required": ["id"],
    },
}

EL_FOLLOW_CREATE = {
    "name": "el_follow_create",
    "description": (
        "Follow one registry entry: give thesis_id for a view or pack_id for a pack, never both. Saves "
        "the caller-owned Follow Card on this machine and returns its next check date. Following the same "
        "entry again keeps the existing card and baseline."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "thesis_id": {"type": "string", "description": "A view's thesis_id from el_list_registry."},
            "pack_id": {"type": "string", "description": "A pack id from el_list_registry."},
        },
    },
}

EL_FOLLOW_CHECK = {
    "name": "el_follow_check",
    "description": (
        "Check local Follow Cards for new evidence. With follow_id checks that card. With no arguments "
        "checks every card that is due and not already awaiting review. An update needing review never "
        "replaces the stored card. Set accept_next only after the user has reviewed the change and said "
        "to accept it; unattended runs refuse it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "follow_id": {"type": "string", "description": "A follow id from el_follow_list."},
            "follow_card": {"type": "object",
                            "description": "A complete Follow Card to check without saving it locally."},
            "accept_next": {
                "type": "boolean",
                "description": "Move follow_id to the new baseline. Requires the user's explicit review.",
            },
        },
    },
}

EL_FOLLOW_LIST = {
    "name": "el_follow_list",
    "description": (
        "List the Follow Cards stored on this machine with next check date and state (waiting, due, "
        "needs review). Local only: makes no network call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "due_only": {"type": "boolean", "description": "Only list follows that are due or need review."},
        },
    },
}


_THEMES = ["ai_compute", "optical_cpo", "custom_asic", "ai_power_thermal", "physical_ai", "space_infrastructure"]
_STOP = (
    "Stop at the person: relay statuses and everything under needs_human, then stop. Never change the "
    "hypothesis, a threshold or a status yourself, and never say what to buy, sell, size or time."
)

EL_PLAN_THESIS = {
    "name": "el_plan_thesis",
    "description": (
        "Step 1 for the user's OWN investment thesis. Sends the thesis text to EquityLayer, which stores nothing, "
        "and returns candidate variables from a fixed catalog with cadence, latest period, caveats and coverage "
        "gaps. Choose variables only from these candidates, read every caveat, and tell the user about gaps. "
        "Selecting variables takes care: do it with the user. " + _NOT_ADVICE
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "thesis_text": {"type": "string", "description": "The thesis in the user's words, any language."},
            "theme_id": {"type": "string", "enum": _THEMES,
                         "description": "Optional theme; adds its company universe to the search."},
            "entities": {"type": "array", "items": {"type": "string"},
                         "description": "Companies meant, as ticker or name, e.g. 3363.TWO or Coherent."},
            "keywords": {"type": "array", "items": {"type": "string"},
                         "description": "Extra terms, e.g. revenue, gross margin, orders."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 60, "description": "Default 25."},
        },
        "required": ["thesis_text"],
    },
}

EL_GET_VARIABLE = {
    "name": "el_get_variable",
    "description": (
        "Read one catalog variable: unit, cadence, caveat, scope breaks and recent readings, so thresholds can "
        "be set from real levels. A withheld value is null with its reason: treat it as no data, never guess it."
    ),
    "parameters": {
        "type": "object",
        "properties": {"variable": {"type": "string", "description": "A v:... id from el_plan_thesis."}},
        "required": ["variable"],
    },
}

EL_HARNESS_SAVE = {
    "name": "el_harness_save",
    "description": (
        "Save the user's thesis harness on this machine (EquityLayer keeps no copy). The harness has four parts: "
        "hypothesis (one falsifiable sentence), why, tracking (links: id, must_hold, variables, runner "
        "program|rules|llm_draft|human, expected_by YYYY-MM-DD or expected_note, if_late, if_against, rules "
        "[{variable, if: '>= N' | '< N' | 'a..b', means: strengthens|weakens|no_material_change|"
        "insufficient_evidence, say}]) and wrong_if (consecutive | average | below_baseline_count | human). "
        "Rule variables must be in that link's variables; thresholds are the user's judgment, say so in `say`. "
        "EquityLayer validates it before it is stored. Pass harness_id to update a saved harness."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "harness": {"type": "object", "description": "The full harness object as check_thesis_harness expects."},
            "harness_id": {"type": "string", "description": "Existing local id to replace. Omit to create."},
        },
        "required": ["harness"],
    },
}

EL_HARNESS_CHECK = {
    "name": "el_harness_check",
    "description": (
        "Check a saved harness against the latest readings. Returns each link's status (not_due, seen, against, "
        "late, no_data), wrong_if results, needs_human items, what changed since the saved baseline, and next "
        "due date. With harness_id checks that one; with no arguments checks every harness that is due; with "
        "`harness` checks an unsaved draft. no_data is not good news. The new baseline is kept only after the "
        "user says they have read the result (el_harness_seen). " + _STOP
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "harness_id": {"type": "string", "description": "A local id from el_harness_list."},
            "harness": {"type": "object", "description": "An unsaved draft harness to check without storing it."},
        },
    },
}

EL_HARNESS_SEEN = {
    "name": "el_harness_seen",
    "description": (
        "Call only after the user has said they read the latest check. Saves that check's next_baseline so the "
        "next check reports only what moved since. Scheduled runs are refused."
    ),
    "parameters": {
        "type": "object",
        "properties": {"harness_id": {"type": "string", "description": "A local id from el_harness_list."}},
        "required": ["harness_id"],
    },
}

EL_HARNESS_LIST = {
    "name": "el_harness_list",
    "description": (
        "List the thesis harnesses saved on this machine with last check, link statuses, needs-you count, next "
        "due date and state. With harness_id returns that harness in full (to show or edit it). Local only."
    ),
    "parameters": {
        "type": "object",
        "properties": {"harness_id": {"type": "string", "description": "Optional local id to open in full."}},
    },
}
