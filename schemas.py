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
        "gaps. Show the markdown, tell the user about caveats and gaps, then STOP and ask which variables, "
        "thresholds and wrong_if conditions they want. Do not draft-save or check a harness in the same turn. "
        "Choose only ids from these candidates. " + _NOT_ADVICE
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
        "EquityLayer validates it before it is stored. Call this only after the user has confirmed the variables, "
        "thresholds and wrong_if in this conversation; never on your own initiative. Pass harness_id to update."
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


EL_PROFILE_GET = {
    "name": "el_profile_get",
    "description": (
        "Read the person's local EquityLayer research profile (sectors, whether they had a view, how often to "
        "check, language), the theses saved on this machine, and the sector options with their live coverage. "
        "Call it first when the person starts or returns, so you skip questions already answered. Local only."
    ),
    "parameters": {"type": "object", "properties": {}},
}

EL_PROFILE_SAVE = {
    "name": "el_profile_save",
    "description": (
        "Save the person's answers from the setup steps to their local research profile, merging with what is "
        "saved. Only save what the person chose. Local only; never sent to EquityLayer. Refused in scheduled runs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sectors": {"type": "array", "items": {"type": "string", "enum": [
                "optical_cpo", "space_infrastructure", "custom_asic", "physical_ai", "other"]},
                "description": "Sectors the person chose, in their order."},
            "path": {"type": "string", "enum": ["curated", "own_view", "formed_view"],
                     "description": "How they follow the sector: curated readings, their own view, or a view formed with your questions."},
            "has_view": {"type": "boolean", "description": "True if they came with a view of their own."},
            "check": {"type": "string", "enum": ["daily", "weekly", "manual"], "description": "How often to check."},
            "check_time": {"type": "string", "description": "HH:MM, 24-hour, for daily or weekly checks."},
            "timezone": {"type": "string", "description": "Area/City, for example Asia/Taipei."},
            "language": {"type": "string", "description": "Language tag the person writes in, for example en or zh-Hant."},
        },
    },
}


EL_WATCH_SAVE = {
    "name": "el_watch_save",
    "description": (
        "Save a watchlist on this machine: 1 to 8 EquityLayer variable ids the person follows without a thesis "
        "(the curated readings for a sector). Use only ids from el_plan_thesis candidates. Call it only after the "
        "person says yes to the list. Pass watch_id to update an existing watchlist. Local only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title, for example \"CPO curated readings\"."},
            "variables": {"type": "array", "items": {"type": "string"}, "description": "Variable ids, v:..."},
            "theme": {"type": "string", "enum": ["optical_cpo", "space_infrastructure", "custom_asic", "physical_ai"]},
            "watch_id": {"type": "string", "description": "Existing watchlist id to update."},
        },
        "required": ["title", "variables"],
    },
}

EL_WATCH_CHECK = {
    "name": "el_watch_check",
    "description": (
        "Check watchlists: latest readings, new periods since the person last read, recent official events "
        "(exchange and issuer releases) and what is due next. With no watch_id it checks every watchlist that is "
        "due or unread. Returns markdown to show as is, and report_total (0 means nothing new). It never marks a "
        "check as read; the person does that with el_watch_seen. Also refreshes the local dashboard."
    ),
    "parameters": {"type": "object", "properties": {"watch_id": {"type": "string"}}},
}

EL_WATCH_SEEN = {
    "name": "el_watch_seen",
    "description": (
        "Mark a watchlist's last check as read after the person says they have read it, so the next check reports "
        "only what is new. Refused in scheduled runs."
    ),
    "parameters": {"type": "object", "properties": {"watch_id": {"type": "string"}}, "required": ["watch_id"]},
}

EL_WATCH_LIST = {
    "name": "el_watch_list",
    "description": "List the watchlists saved on this machine, or open one with its last check. Local only.",
    "parameters": {"type": "object", "properties": {"watch_id": {"type": "string"}}},
}

EL_DASHBOARD_RENDER = {
    "name": "el_dashboard_render",
    "description": (
        "Render the person's local EquityLayer dashboard (what they follow, their theses, what needs them, recent "
        "events, what is due next) to an HTML file on this machine and return its path. Built from local files "
        "only; contacts no one. Hermes Desktop lists it under Artifacts. Pass preview_variables (the live readings "
        "you just showed) to add a 'Live now' preview before anything is saved; it reads them from EquityLayer and "
        "saves nothing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "preview_variables": {"type": "array", "items": {"type": "string"},
                                  "description": "Up to 8 variable ids to show as a not-saved preview."},
            "preview_title": {"type": "string", "description": "Short title, for example \"CPO live readings\"."},
            "preview_theme": {"type": "string", "enum": ["optical_cpo", "space_infrastructure", "custom_asic", "physical_ai"],
                              "description": "The sector of the preview, so the dashboard links to its page."},
        },
    },
}
