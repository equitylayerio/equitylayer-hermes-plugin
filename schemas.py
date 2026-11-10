"""Tool schemas the Hermes model reads. Each tool name is declared in plugin.yaml."""

_NOT_ADVICE = "Results are research evidence, not investment advice."

_FORMAT = {
    "type": "string",
    "enum": ["markdown", "json"],
    "description": "markdown (default) returns a chat-ready summary. json returns the raw EquityLayer payload.",
}

# The nine tools Hermes registers: one tracked object, three levels.

EL_PROFILE = {'name': 'el_profile',
 'description': "Read or save the person's local EquityLayer profile. With no fields it returns the profile, what "
                'they already track, and the sector options with live coverage; call it first when they start or '
                'return. With fields it saves only what they chose. Local only; refused in scheduled runs when '
                'saving.',
 'parameters': {'type': 'object',
                'properties': {'sectors': {'type': 'array',
                                           'items': {'type': 'string',
                                                     'enum': ['optical_cpo',
                                                              'space_infrastructure',
                                                              'custom_asic',
                                                              'physical_ai',
                                                              'other']},
                                           'description': 'Sectors the person chose, in their order.'},
                               'path': {'type': 'string',
                                        'enum': ['curated', 'own_view', 'formed_view'],
                                        'description': 'How they follow the sector: curated readings, their own '
                                                       'view, or a view formed with your questions.'},
                               'has_view': {'type': 'boolean',
                                            'description': 'True if they came with a view of their own.'},
                               'check': {'type': 'string',
                                         'enum': ['daily', 'weekly', 'manual'],
                                         'description': 'How often to check.'},
                               'check_time': {'type': 'string',
                                              'description': 'HH:MM, 24-hour, for daily or weekly checks.'},
                               'timezone': {'type': 'string', 'description': 'Area/City, for example Asia/Taipei.'},
                               'language': {'type': 'string',
                                            'description': 'Language tag the person writes in, for example en or '
                                                           'zh-Hant.'}}}}

EL_PLAN = {'name': 'el_plan',
 'description': 'Find catalog variables for a sector or a thesis. Sends the text to EquityLayer, which stores '
                'nothing, and returns candidate variables with category, cadence, latest period, caveats and '
                'coverage gaps. Choose only ids from these candidates, and ask the person before saving anything. '
                'Results are research evidence, not investment advice.',
 'parameters': {'type': 'object',
                'properties': {'thesis_text': {'type': 'string',
                                               'description': "The thesis in the user's words, any language."},
                               'theme_id': {'type': 'string',
                                            'enum': ['ai_compute',
                                                     'optical_cpo',
                                                     'custom_asic',
                                                     'ai_power_thermal',
                                                     'physical_ai',
                                                     'space_infrastructure'],
                                            'description': 'Optional theme; adds its company universe to the '
                                                           'search.'},
                               'entities': {'type': 'array',
                                            'items': {'type': 'string'},
                                            'description': 'Companies meant, as ticker or name, e.g. 3363.TWO or '
                                                           'Coherent.'},
                               'keywords': {'type': 'array',
                                            'items': {'type': 'string'},
                                            'description': 'Extra terms, e.g. revenue, gross margin, orders.'},
                               'limit': {'type': 'integer',
                                         'minimum': 1,
                                         'maximum': 60,
                                         'description': 'Default 25.'}},
                'required': ['thesis_text']}}

EL_GET_VARIABLE = {'name': 'el_get_variable',
 'description': 'Read one catalog variable: unit, cadence, caveat, scope breaks and recent readings, so thresholds '
                'can be set from real levels. A withheld value is null with its reason: treat it as no data, never '
                'guess it.',
 'parameters': {'type': 'object',
                'properties': {'variable': {'type': 'string', 'description': 'A v:... id from el_plan.'}},
                'required': ['variable']}}

EL_TRACK = {'name': 'el_track',
 'description': 'Save what the person chose to track, on this machine. A tracked item has one of three levels: '
                "readings (curated readings, no view needed), your thesis (the same readings plus the person's own "
                'thesis and wrong_if) and EquityLayer thesis (a published Research Pack the person follows). Give '
                'variables (with a title and theme) to follow readings; give harness to save their own thesis; give '
                'pack_id to follow a published Research Pack. To add a thesis to readings they already follow, pass '
                "that item_id with harness: the readings stay under the same id and become the thesis's evidence. To "
                'change a saved thesis (thresholds, a person_reads answer), pass its item_id with the full updated '
                'harness. Call it only after the person says yes in this conversation. The harness has four parts: '
                'hypothesis (one falsifiable sentence), why, tracking (links: id, must_hold, variables, runner '
                'program|rules|llm_draft|human, expected_by YYYY-MM-DD or expected_note, if_late, if_against, rules '
                "[{variable, if: '>= N' | '< N' | 'a..b', means: "
                'strengthens|weakens|no_material_change|insufficient_evidence, say}]) and wrong_if (consecutive | '
                "average | below_baseline_count | human). Rule variables must be in that link's variables; "
                "thresholds are the person's call, say so in `say`. EquityLayer validates a thesis before it is "
                'stored.',
 'parameters': {'type': 'object',
                'properties': {'item_id': {'type': 'string',
                                           'description': 'An existing item to update or add a level to (from '
                                                          'el_list).'},
                               'title': {'type': 'string',
                                         'description': 'Short title for readings, e.g. "CPO curated readings".'},
                               'theme': {'type': 'string',
                                         'enum': ['optical_cpo',
                                                  'space_infrastructure',
                                                  'custom_asic',
                                                  'physical_ai']},
                               'variables': {'type': 'array',
                                             'items': {'type': 'string'},
                                             'description': '1 to 8 variable ids (v:...).'},
                               'harness': {'type': 'object',
                                           'description': 'The full harness object as check_thesis_harness expects.'},
                               'pack_id': {'type': 'string',
                                           'description': 'A published Research Pack id from el_research_pack.'}}}}

EL_CHECK = {'name': 'el_check',
 'description': 'Check what the person tracks. With no item_id it checks every item that is due or unread, at every '
                'level, and returns markdown to show as is plus report_total (0 means nothing new). With item_id it '
                'checks that one. It never marks anything as read; the person does that through el_seen. Also '
                'refreshes the dashboard. Stop at the person: relay statuses and everything under needs_human, then '
                'stop. Never change the hypothesis, a threshold or a status yourself, and never say what to buy, '
                'sell, size or time.',
 'parameters': {'type': 'object',
                'properties': {'item_id': {'type': 'string', 'description': 'Optional id from el_list.'}}}}

EL_SEEN = {'name': 'el_seen',
 'description': 'After the person says they have read a check, keep it as what the next check compares with. For a '
                "followed Research Pack, this instead moves to the Pack's new version, which is a separate choice: "
                'call it with accept_update true only after the person explicitly says to accept the update. Refused '
                'in scheduled runs.',
 'parameters': {'type': 'object',
                'properties': {'item_id': {'type': 'string'},
                               'accept_update': {'type': 'boolean',
                                                 'description': 'Followed Packs only: the person accepted the '
                                                                'update.'}},
                'required': ['item_id']}}

EL_LIST = {'name': 'el_list',
 'description': 'List everything the person tracks with its level, last check and state, or open one item. Local '
                'only.',
 'parameters': {'type': 'object',
                'properties': {'item_id': {'type': 'string', 'description': 'Optional id to open.'}}}}

EL_DASHBOARD_RENDER = {'name': 'el_dashboard_render',
 'description': "Render the person's local EquityLayer dashboard (what they follow, their theses, what needs them, "
                'recent events, what is due next) to an HTML file on this machine and return its path. Built from '
                'local files only; contacts no one. Hermes Desktop lists it under Artifacts. Pass preview_variables '
                "(the live readings you just showed) to add a 'Live now' preview before anything is saved; it reads "
                'them from EquityLayer and saves nothing.',
 'parameters': {'type': 'object',
                'properties': {'preview_variables': {'type': 'array',
                                                     'items': {'type': 'string'},
                                                     'description': 'Up to 8 variable ids to show as a not-saved '
                                                                    'preview.'},
                               'preview_title': {'type': 'string',
                                                 'description': 'Short title, for example "CPO live readings".'},
                               'preview_theme': {'type': 'string',
                                                 'enum': ['optical_cpo',
                                                          'space_infrastructure',
                                                          'custom_asic',
                                                          'physical_ai'],
                                                 'description': 'The sector of the preview, so the dashboard links '
                                                                'to its page.'}}}}

EL_RESEARCH_PACK = {'name': 'el_research_pack',
 'description': "EquityLayer's published research. action=list returns current Research Packs (it may be empty: say "
                'so plainly); action=read reads one with its thesis, tracked variables and next check; '
                'action=scorecard shows how its claims resolved. To follow a Pack, use el_track with pack_id. '
                'Results are research evidence, not investment advice.',
 'parameters': {'type': 'object',
                'properties': {'action': {'type': 'string', 'enum': ['list', 'read', 'scorecard']},
                               'pack_id': {'type': 'string'},
                               'symbols': {'type': 'array', 'items': {'type': 'string'}},
                               'publisher': {'type': 'string'}}}}

REGISTERED = (EL_PROFILE, EL_PLAN, EL_GET_VARIABLE, EL_TRACK, EL_CHECK, EL_SEEN, EL_LIST, EL_DASHBOARD_RENDER, EL_RESEARCH_PACK)
