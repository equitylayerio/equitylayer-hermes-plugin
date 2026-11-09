# EquityLayer for Hermes Agent

**Research CPO, Physical AI and space infrastructure with your own AI. EquityLayer gives Hermes the tracked variables, source rules and caveats; you write the thesis; Hermes checks it every day and tells you what moved, what is late and what needs you. It never tells you what to trade.**

Ask an AI whether robots are really scaling, or whether co-packaged optics is shipping, and you usually get a confident summary with no dates, no sources and no way to tell later whether it still holds. This plugin turns your own view into something Hermes can check against official readings: issuer filings, exchange open data and company statements, each with its period, its source and what it cannot show.

You state a thesis in your own words. EquityLayer's public MCP maps it to a catalog of tracked variables (shipments, segment revenue, orders, capex, issuer statements) with caveats and coverage gaps. You and Hermes write the four parts: **hypothesis, why, tracking, wrong_if**. The plugin stores that harness and its baseline on your machine, and a daily Hermes job checks it against the latest readings. EquityLayer stores neither the thesis nor the harness.

**Coverage today (2026-11-09):**

| Theme | What you can track now |
| --- | --- |
| CPO and optical networking | The deepest theme: 28 variables across Taiwan, US and Japan suppliers (revenue, segments, capex, issuer statements). |
| Physical AI | Robot lidar shipments (Hesai), Teradyne Robotics revenue, Tesla's Optimus statements and Nabtesco orders are readable. Most robot-maker readings are still withheld under source-rights review and show as "no data". |
| Space infrastructure | In research. Launch and satellite variables are not in the catalog yet, so a space thesis will mostly show gaps. |

The plugin says which readings are missing or withheld instead of guessing.

```
you: "Robots reach volume by 2028, and component suppliers show it in shipments first"
        │
        ▼  el_plan_thesis ──► EquityLayer MCP: candidate variables, caveats, gaps (stores nothing)
you + Hermes pick variables, set your own thresholds, write wrong_if
        │
        ▼  el_harness_save ──► validated by EquityLayer, saved under plugin-data/equitylayer/
        ▼  el_harness_check (now, or daily via cron)
   link status: 🟢 seen · 🔴 against · 🟠 late · ⚪ no data · ⏳ not due
   wrong_if: fired / not fired / needs you
   changed since your baseline · next due date · caveats · sources
        │
        ▼  stops at the person: anything new waits for you to read it before it becomes your baseline
```

## Why a plugin and not just an MCP connector

A plain `mcp.json` connector gives the model EquityLayer's tools. It cannot remember your harness, keep a baseline, run on a schedule, or hold back a baseline until a person has read the result. This plugin adds:

- **Local harness and baseline storage** (one JSON file per harness, written atomically, under Hermes's `plugin-data/equitylayer/`).
- **A scheduled check** (`/blueprint equitylayer:thesis-check` or a ready `hermes cron create` line) that only contacts EquityLayer for harnesses that are due, stays silent when nothing moved, and repeats an unread alert instead of marking it read.
- **Readable statuses**: link table, wrong_if results, a "Needs you" block, what changed since your baseline, caveats and license attributions.
- **Slash commands** (`/el plan`, `/el check`, `/el seen`, ...) that work without asking the model.
- **A bundled skill** (`equitylayer-thesis-harness`) that teaches the model the careful step (choose only listed variables, read every caveat, thresholds are your judgment) and the stop rule.

## Install

Requires Hermes Agent 0.23.0 or later.

```bash
hermes plugins install https://github.com/equitylayerio/equitylayer-hermes-plugin --enable
```

No account, key or sign-in is needed. The default endpoint is `https://equitylayer.io/mcp`.

Using EquityLayer from another agent (Claude, Codex, Cursor) instead of Hermes? See [equitylayerio/equitylayer-research-onboarding](https://github.com/equitylayerio/equitylayer-research-onboarding).

## 60-second quick start

In a Hermes chat:

1. **State your thesis.**
   > My thesis: robots move from pilots to volume production by the end of 2028, and component suppliers show it in shipments before humanoid makers report robot revenue. Help me track it with EquityLayer. Theme: physical_ai. Show me what I could track first; don't save anything yet.

   Hermes calls `el_plan_thesis` and shows candidate variables with their caveats and gaps. Or run it directly:

   ```text
   /el plan --theme physical_ai Robots reach volume production by 2028, and component suppliers show it in shipments first.
   ```

2. **Pick variables and thresholds with Hermes.** It reads recent levels with `el_get_variable`, proposes the four parts with thresholds marked as your judgment, and saves only after you confirm.
3. **Check it now.**

   ```text
   /el check
   ```

   You get each link's status, wrong_if results, what needs you, caveats, sources and the next due date. A slash-command check is read by you directly, so it becomes your baseline. When the model runs a check for you, it asks you to confirm you've read it first.
4. **Check it every day.**

   ```text
   /el schedule 09:00 Asia/Taipei
   ```

   Paste the printed `hermes cron create` line, or use `/blueprint equitylayer:thesis-check`. The job is silent unless something moved or needs you.

## Commands

| Command | What it does |
| --- | --- |
| `/el plan [--theme ID] [--company X] <thesis>` | Candidate variables for your thesis. Nothing is stored. |
| `/el var <variable id>` | Unit, cadence, caveat, scope breaks and recent readings of one variable. |
| `/el theses` | Harnesses saved on this machine, with last check, statuses and next due date. |
| `/el show <id>` | The four parts of one harness. |
| `/el check [id]` | Check one harness now, or every harness that is due. |
| `/el seen <id>` | Mark the last check as read so it becomes your baseline. |
| `/el remove <id>` | Delete a harness from this machine. |
| `/el schedule [HH:MM] [Area/City]` | Print the daily cron command and blueprint. |
| `/el registry` | Published EquityLayer Research Packs. It says so plainly when none is published. |
| `/el pack`, `/el scorecard`, `/el follow`, `/el follows`, `/el follow-check`, `/el unfollow` | Read and follow a published Research Pack. |

Themes for `--theme`: `ai_compute`, `optical_cpo`, `custom_asic`, `ai_power_thermal`, `physical_ai`, `space_infrastructure`.

## Tools the model can call

| Tool | Purpose |
| --- | --- |
| `el_plan_thesis` | Map the user's thesis to catalog variables, caveats and gaps. |
| `el_get_variable` | Read one variable's levels before setting a threshold. |
| `el_harness_save` | Validate with EquityLayer, then save the harness locally. |
| `el_harness_check` | Check one harness, every due harness, or an unsaved draft. |
| `el_harness_seen` | Keep the new baseline after the user says they read it. Refused in scheduled runs. |
| `el_harness_list` | List local harnesses, or open one in full. |
| `el_list_registry`, `el_get_pack`, `el_scorecard` | Published research. |
| `el_follow_create`, `el_follow_check`, `el_follow_list` | Local Follow Cards for a published Pack. |

There is no tool that deletes a harness or changes its statuses. Deleting is a slash command only.

## What it will not do

- It never says what to buy, sell, size or time, and never turns a result into a portfolio.
- It never changes your hypothesis, thresholds or statuses on its own.
- `late`, `against`, a fired `wrong_if` and every `needs_human` item are shown to you as such, and the agent stops there.
- `no_data` is never shown as good news. A withheld value (a paid Pack, or a source whose rights are under review) decides nothing.
- A scheduled run never marks a check that has something new as read: that harness is checked again each day and the alert repeats until you have seen it. A check with nothing new (no change, nothing needing you) advances the baseline on its own.

## Disclosures

- **Network:** every call goes over HTTPS to `https://equitylayer.io/mcp` (and `/mcp/full` for `get_variable`). The URL setting accepts only that host, or `http://localhost` for development. No other host is contacted.
- **What is sent:** only the tool arguments: your thesis text for `el_plan_thesis`, your harness and last baseline for checks, and the ids you ask about. EquityLayer's server reports that it stores neither the thesis nor the harness (`"stored": false` in its responses). No user id, email or telemetry is sent; the User-Agent is `EquityLayerHermesPlugin/0.2`.
- **Local data:** harnesses, baselines, a 30-entry check history and Follow Cards are written under Hermes's `plugin-data/equitylayer/` for the active profile. Nothing else on disk is read.
- **No credentials:** the plugin holds no key and never pays. A paid or gated response comes back as `entitlement_or_payment_required` with a link; the plugin does not authenticate or pay for you.
- **No shell commands, no background processes, no self-updates.** Scheduling uses Hermes's own cron.
- **Data licenses:** readings carry the attribution their license requires (for example Taipei Exchange open data under Taiwan's Open Government Data License), and the plugin keeps it in what it shows.
- **Not investment advice.** EquityLayer reports which variable moved and which link it affects, then stops. The judgment is yours.

## Configuration

| Setting | Default | Notes |
| --- | --- | --- |
| `mcp_url` | `https://equitylayer.io/mcp` | `http://localhost:<port>/mcp` is accepted for development. |

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

The example harnesses in `tests/harness_demo.json` (CPO) and `tests/harness_physical_ai.json` (Physical AI) are illustrative user theses for tests. It is not EquityLayer research or a published view, and its thresholds are arbitrary.

## License

MIT
