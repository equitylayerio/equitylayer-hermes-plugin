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
        "Start here to find EquityLayer research. Lists Research Registry views and packs with "
        "access, freshness and next check date, plus a markdown table. Entries marked locked are not "
        f"available in demo mode. {_NOT_ADVICE}"
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

EL_TEST_THESIS = {
    "name": "el_test_thesis",
    "description": (
        "Test a public EquityLayer view against its retained evidence packs. Prefer thesis_id from the "
        "registry. Saves the pack versions locally so el_thesis_update can compare later. Send a private "
        f"thesis only when the user asks; demo mode refuses it. {_NOT_ADVICE}"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "thesis_id": {"type": "string", "description": "Public view id from el_list_registry."},
            "thesis": {"type": "object", "description": "Caller-supplied private Thesis Card. Off in demo mode."},
            "last_pack_versions": {"type": "array", "items": {"type": "object"},
                                   "description": "Optional caller-owned pack baselines."},
            "format": _FORMAT,
        },
    },
}

EL_THESIS_UPDATE = {
    "name": "el_thesis_update",
    "description": (
        "Check whether a public view or its supporting pack changed since the saved baseline. Uses the "
        "baseline saved by el_test_thesis unless since_pack_versions is given. A current result is free; "
        f"this route has no payment. {_NOT_ADVICE}"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "thesis_id": {"type": "string", "description": "Public view id from el_list_registry."},
            "since_thesis_version": {"type": "string", "description": "Optional last view version seen."},
            "since_pack_versions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"pack_id": {"type": "string"}, "version": {"type": "string"}},
                    "required": ["pack_id", "version"],
                },
                "description": "Optional pack baselines. Defaults to the locally saved baseline.",
            },
            "portable_research_card": {"type": "object",
                                       "description": "Complete private research card. Off in demo mode."},
            "format": _FORMAT,
        },
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
