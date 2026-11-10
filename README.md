# EquityLayer for Hermes Agent

**Research CPO, custom AI chips or space infrastructure with your own AI. EquityLayer gives Hermes the tracked variables, source rules and caveats; you write the thesis; Hermes checks it every day and tells you what moved, what is late and what needs you. It never tells you what to trade.**

Ask an AI whether co-packaged optics is really shipping, or whether launch backlogs are turning into revenue, and you usually get a confident summary with no dates, no sources and no way to tell later whether it still holds. This plugin turns your own view into something Hermes can check against official readings: issuer filings, exchange open data and company statements, each with its period, its source and what it cannot show.

You state a thesis in your own words. EquityLayer's public MCP maps it to a catalog of tracked variables (shipments, segment revenue, orders, capex, issuer statements) with caveats and coverage gaps. You and Hermes write the four parts: **hypothesis, why, tracking, wrong_if**. The plugin stores that harness and its baseline on your machine, and a daily Hermes job checks it against the latest readings. EquityLayer stores neither the thesis nor the harness.

**Coverage today (2026-11-10):**

| Theme | What you can track |
| --- | --- |
| CPO and optical networking | Live now: 28 variables across Taiwan, US and Japan suppliers (revenue, segments, capex, issuer statements). |
| Custom AI chips (ASIC) | Live now: design-service and foundry suppliers' monthly revenue and filings (Taiwan open data, SEC). |
| Space infrastructure | Being added: launch and satellite variables are in review and not in the live catalog yet. Until they land, a space thesis mostly shows gaps. |
| Physical AI | Variables listed, most readings withheld while source rights are reviewed. |

The plugin says which readings are missing or withheld instead of guessing.

```
you: /equitylayer:start  →  sector  →  live readings and your dashboard (before anything is saved)
        │
        ▼  el_track: one tracked item, three levels
           readings ─────► + your thesis (hypothesis, why, tracking, wrong_if) ─────► or EquityLayer's thesis (a Pack)
        │
        ▼  el_check (now, or one daily job created in the chat)
   new readings · link status 🟢 seen · 🔴 against · 🟠 late · ⚪ no data · ⏳ not due
   wrong_if fired / not fired / needs you · official events · what is due next
        │
        ▼  stops at the person: nothing becomes your baseline until you say you read it (el_seen)
```

## Why a plugin and not just an MCP connector

A plain `mcp.json` connector gives the model EquityLayer's tools. It cannot remember your harness, keep a baseline, run on a schedule, or hold back a baseline until a person has read the result. This plugin adds:

- **One tracked object, three levels:** follow a sector's curated readings, add your own thesis to them (same id; the readings stay as its evidence), or follow EquityLayer's published thesis. Stored as atomic JSON under Hermes's `plugin-data/equitylayer/`.
- **Guided start** (`/equitylayer:start`): four decisions with a recommended option each, live readings first.
- **One daily check** created from the chat (or `/blueprint equitylayer:daily-check`) that only contacts EquityLayer for items that are due, stays silent when nothing is new, and repeats an unread alert instead of marking it read.
- **A local dashboard in the chat:** the thesis first with a plain status, then the readings as evidence by supply-chain step, with what each company does (from its own disclosures), official events and what is due next. Built by code from local files; contacts no one.
- **Recall across chats:** each new chat starts with your profile and a short list of what you track, rebuilt from the local files.
- **Five slash commands** (`/el start`, `/el dashboard`, `/el check`, `/el seen`, `/el list`) that work without asking the model.

## Install

Requires Hermes Agent 0.23.0 or later.

```bash
hermes plugins install https://github.com/equitylayerio/equitylayer-hermes-plugin --enable
```

No account, key or sign-in is needed. The default endpoint is `https://equitylayer.io/mcp`.

Using EquityLayer from another agent (Claude, Codex, Cursor) instead of Hermes? See [equitylayerio/equitylayer-research-onboarding](https://github.com/equitylayerio/equitylayer-research-onboarding).

## Start here

In a Hermes chat (terminal, Desktop or Webapp), type:

```text
/equitylayer:start
```

or say *"Help me start researching with EquityLayer."* Four decisions, each with a recommended option, so answering "yes" all the way still ends somewhere useful:

1. **Sector:** CPO and optical networking (recommended), space infrastructure, custom AI chips, or something else. Hermes then shows three live readings for it before asking you for anything.
2. **How to follow it:** the curated readings (recommended, no view needed), your own view in one sentence, or three short questions that help you form one. EquityLayer never writes a view for you.
3. **One card to approve:** the readings, and for a view also your thresholds (marked as your judgment) and what would prove you wrong.
4. **Read it, and how often to check:** every day at 09:00 (recommended), every Monday, or only when you ask. Hermes sets up the check in that chat.

A local dashboard (`/el dashboard`, or Artifacts in Hermes Desktop) shows what you follow, your theses, what needs you, recent official events and what is due next. Hermes remembers your answers, so next time it opens with your dashboard.

## By hand

```text
/el check          # check everything that is due; you read it, so it becomes your baseline
/el seen <id>      # mark one item's last check as read
/el list           # everything you track, with its level
/el dashboard      # your dashboard
/el schedule 09:00 Asia/Taipei   # print the daily job and blueprint
```

## Commands

| Command | What it does |
| --- | --- |
| `/equitylayer:start` or `/el start` | Guided setup in four decisions. Start here. |
| `/el dashboard` | Your dashboard: the thesis first, readings as evidence. |
| `/el check [id]` | Check everything that is due, or one item. You read it, so it becomes your baseline. |
| `/el seen <id>` | Mark an item's last check as read. |
| `/el list [id]` | Everything you track with its level, or one item in full. |

Everything else works in plain words, for example "add my own thesis to my CPO readings" or "is there a Research Pack for CPO?". `/el remove <id>` deletes an item from this machine; no tool deletes anything. Following a Pack also follows the readings it watches, as one item. When one of them has new data, saying you've read it moves the Pack's baseline too; a new revision of the Pack replaces its card only when you accept it.

## Tools the model can call

Nine tools. A tracked item has one of three levels: **readings**, **your thesis**, or **EquityLayer thesis** (a followed Research Pack).

| Tool | Purpose |
| --- | --- |
| `el_profile` | Read or save the person's profile; returns what they track and the sector options with live coverage. |
| `el_plan` | Find catalog variables for a sector or a thesis, with caveats and gaps. |
| `el_get_variable` | Read one variable's levels, and what its company does, before showing or setting a threshold. |
| `el_track` | Save a tracked item at any level, add a thesis to readings already followed (same id, readings kept), or update a thesis. |
| `el_check` | Check everything due, or one item. Never marks anything as read. |
| `el_seen` | Keep a check as the new baseline after the person says they read it; for a followed Pack, accept an update only when they say so. Refused in scheduled runs. |
| `el_list` | List tracked items, or open one. |
| `el_dashboard_render` | Write the local dashboard and show it in the chat. |
| `el_research_pack` | List, read or score EquityLayer's published Research Packs. |

## What it will not do

- It never says what to buy, sell, size or time, and never turns a result into a portfolio.
- It never changes your hypothesis, thresholds or statuses on its own.
- `late`, `against`, a fired `wrong_if` and every `needs_human` item are shown to you as such, and the agent stops there.
- `no_data` is never shown as good news. A withheld value (a paid Pack, or a source whose rights are under review) decides nothing.
- A scheduled run never marks a check that has something new as read: that item is checked again each day and the alert repeats until you have seen it. A check with nothing new (no change, nothing needing you) advances the baseline on its own.

## Disclosures

- **Network:** every call goes over HTTPS to `https://equitylayer.io/mcp` (and `/mcp/full` on the same server for events and due dates). The URL setting accepts only that host, or `http://localhost` for development. No other host is contacted.
- **What is sent:** only the tool arguments: your thesis or sector text for `el_plan`, your harness and last baseline for checks, and the variable ids you ask about or follow (events and due dates for them come from the same server's `/mcp/full` tool list). EquityLayer's server reports that it stores neither the thesis nor the harness (`"stored": false` in its responses). No user id, email or telemetry is sent; the User-Agent is `EquityLayerHermesPlugin/0.4`.
- **Local data:** harnesses, baselines, a 30-entry check history, Follow Cards, watchlists, the dashboard page and your research profile (sectors, whether you came with a view, check time, timezone, language; fixed values only) are written under Hermes's `plugin-data/equitylayer/` for the active profile. Nothing else on disk is read.
- **Recall in new chats:** at the start of each new chat the plugin adds a short system prompt section (Hermes's `register_system_prompt_section`) listing your research profile, watchlists and saved harnesses: id, title, last check date and state, at most 2,000 characters. It is rebuilt from the local files for every new chat, nothing is written to Hermes memory, and nothing extra is sent to EquityLayer. Within a chat the list stays as it was when the chat started, and Hermes keeps the system prompt with that chat's saved history, so a title stays in older chats after you delete its harness. The section goes to whichever model provider you use with Hermes, like the rest of the prompt. Turn it off with `recall_in_new_chats: false`.
- **No credentials:** the plugin holds no key and never pays. A paid or gated response comes back as `entitlement_or_payment_required` with a link; the plugin does not authenticate or pay for you.
- **No shell commands, no background processes, no self-updates.** Scheduling uses Hermes's own cron.
- **Data licenses:** readings carry the attribution their license requires (for example Taipei Exchange open data under Taiwan's Open Government Data License), and the plugin keeps it in what it shows.
- **Not investment advice.** EquityLayer reports which variable moved and which link it affects, then stops. The judgment is yours.

## Configuration

| Setting | Default | Notes |
| --- | --- | --- |
| `mcp_url` | `https://equitylayer.io/mcp` | `http://localhost:<port>/mcp` is accepted for development. |
| `recall_in_new_chats` | `true` | List your research profile and saved harnesses (id, title, last check date and state) at the start of each new chat. |

```bash
hermes config set plugins.entries.equitylayer.settings.mcp_url https://equitylayer.io/mcp
```

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install 'httpx>=0.27,<0.29' 'pytest>=8,<9' pyyaml
.venv/bin/python -m pytest -q                      # offline, recorded responses
.venv/bin/python -m pytest -q -m network           # live, against https://equitylayer.io/mcp
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
```

Set `EQUITYLAYER_TEST_MCP_URL=http://localhost:3420/mcp` to run the live tests against a local server.

The example harnesses in `tests/` are illustrative user theses for tests. They are not EquityLayer research or published views, and their thresholds are arbitrary.

## License

MIT
