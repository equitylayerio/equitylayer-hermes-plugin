"""Bring-your-own-thesis tools: plan variables, save the harness locally, check it, stop at the person."""

from __future__ import annotations

import re
from typing import Any

from . import harness_format
from .company_roles import role_for
from .harness_store import HarnessStore, is_due
from .mcp_client import McpError

# Words that turn a thesis into an order. The harness tracks evidence, so they get a warning.
TRADE_WORDS = re.compile(
    r"\b(buy|sell|short (?:it|the)|go long|target price|price target|position siz\w*|stop[- ]loss|"
    r"take[- ]profit|overweight|underweight|allocate)\b",
    re.IGNORECASE,
)
REQUIRED_PARTS = ("hypothesis", "why", "tracking", "wrong_if")
CRON_REFUSAL = {
    "ok": False,
    "error": "person_required",
    "message": "Only a person can mark a check as read. Scheduled runs never do it.",
}


def _text(args: dict, name: str) -> str:
    value = args.get(name)
    return value.strip() if isinstance(value, str) else ""


def _strings(value: Any, limit: int = 20) -> list[str]:
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()][:limit]


def lint_harness(harness: Any, known_ids: set[str] | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors stop a save; warnings are shown to the person."""
    if not isinstance(harness, dict):
        return ["harness must be an object with hypothesis, why, tracking and wrong_if."], []
    # An empty wrong_if is allowed by the server, so it is a warning below, not an error.
    errors = [
        f"`{part}` is missing." for part in REQUIRED_PARTS
        if harness.get(part) is None or (part != "wrong_if" and not harness.get(part))
    ]
    if harness.get("tracking") is not None and not isinstance(harness.get("tracking"), list):
        errors.append("`tracking` must be a list of links.")
    if harness.get("wrong_if") is not None and not isinstance(harness.get("wrong_if"), list):
        errors.append("`wrong_if` must be a list.")
    warnings: list[str] = []
    hypothesis = str(harness.get("hypothesis") or "")
    if hypothesis.rstrip().endswith("?"):
        warnings.append("The hypothesis is a question. It should take a stand that could be wrong.")
    if TRADE_WORDS.search(_free_text(harness)):
        warnings.append(
            "The harness mentions trading. It tracks evidence only; what to buy, sell, size or time stays your call "
            "and is never computed here."
        )
    for link in harness.get("tracking") or []:
        if not isinstance(link, dict):
            continue
        variables = list(link.get("variables") or [])
        if link.get("runner") in ("program", "rules") and variables and not link.get("rules"):
            warnings.append(f"Link `{link.get('id')}` has no rules, so it reports no data until you add thresholds.")
        if not variables and not link.get("variable_gap") and link.get("runner") != "human":
            warnings.append(f"Link `{link.get('id')}` has no variables. Say why in `variable_gap`.")
        if known_ids is not None:
            unknown = [v for v in variables if v not in known_ids]
            if unknown:
                warnings.append(
                    f"Link `{link.get('id')}` uses ids that were not in the last plan: {', '.join(unknown)}."
                )
    for condition in harness.get("wrong_if") or []:
        if isinstance(condition, dict) and condition.get("type") == "consecutive" and not condition.get("from"):
            warnings.append(
                f"wrong_if `{condition.get('id')}` has no `from` date, so readings from before today can fire it. "
                "Set `from` to the day you start tracking."
            )
    if isinstance(harness.get("wrong_if"), list) and not harness["wrong_if"]:
        warnings.append("`wrong_if` is empty, so nothing could show the thesis is wrong.")
    return errors, warnings


def needs_report(result: dict) -> bool:
    """True when a person has something to read: a first check, anything that needs them, or any change."""
    if result.get("needs_human"):
        return True
    changed = result.get("changed")
    if not isinstance(changed, dict):
        return True  # No baseline yet: the person has never seen these statuses.
    return any(changed.get(key) for key in ("variables", "links", "wrong_if", "expected_date_moves", "added_variables"))


def _free_text(harness: dict) -> str:
    """Every field a person writes in words, for the trade-language check."""
    parts = [str(harness.get(k) or "") for k in ("title", "hypothesis", "why", "differs_from")]
    parts += [str(e) for e in harness.get("exposure") or []]
    for link in harness.get("tracking") or []:
        if isinstance(link, dict):
            parts += [str(link.get(k) or "") for k in ("must_hold", "if_late", "if_against", "expected_note", "variable_gap")]
            parts += [str(r.get("say") or "") for r in link.get("rules") or [] if isinstance(r, dict)]
    parts += [str(w.get("label") or "") for w in harness.get("wrong_if") or [] if isinstance(w, dict)]
    return " \n".join(parts)


class HarnessTools:
    """Mixed into EquityLayerTools; relies on its `_call`, `_get_config`, `_in_cron` and `_transport`."""

    _harness_store_factory: Any
    _plan_ids: set[str] | None = None

    # -- plan and variables ----------------------------------------------------------------------

    def _plan(self, args: dict) -> dict:
        thesis_text = _text(args, "thesis_text")
        if len(thesis_text) < 8:
            return {"ok": False, "error": "missing_argument", "argument": "thesis_text",
                    "message": "Write the thesis in a sentence or two (at least 8 characters)."}
        arguments: dict = {"thesis_text": thesis_text[:4000]}
        if _text(args, "theme_id"):
            arguments["theme_id"] = _text(args, "theme_id")
        for key in ("entities", "keywords"):
            values = _strings(args.get(key))
            if values:
                arguments[key] = [v[:40] for v in values]
        if isinstance(args.get("limit"), int) and 1 <= args["limit"] <= 60:
            arguments["limit"] = args["limit"]
        data = self._call("plan_thesis_tracking", arguments)
        candidates = [c for c in data.get("candidates") or [] if isinstance(c, dict)]
        self._plan_ids = {str(c.get("variable")) for c in candidates}
        return {
            "ok": True,
            "stored": False,
            "candidates": [
                {k: c.get(k) for k in ("variable", "name", "entity", "category", "cadence", "unit", "caveat",
                                       "latest_period", "next_reading", "suggested_runner", "readings", "aggregate")
                 if c.get(k) is not None}
                for c in candidates
            ],
            "gaps": data.get("gaps") or [],
            "unmatched_terms": data.get("unmatched_terms") or [],
            "harness_shape": data.get("harness_shape"),
            "boundary": data.get("boundary"),
            "markdown": harness_format.format_plan(data, thesis_text),
        }

    def _variable(self, args: dict) -> dict:
        variable = _text(args, "variable")
        if not variable.startswith("v:"):
            return {"ok": False, "error": "missing_argument", "argument": "variable",
                    "message": "Give a variable id from el_plan_thesis, for example v:3363.two.revenue.monthly."}
        data = self._call("get_variable", {"variable": variable})
        company = role_for(data.get("entity"))
        markdown = harness_format.format_variable(data)
        if company:
            markdown += (f"\n\n**What {company['name'] or data.get('entity')} does** ({company['step']}): "
                         f"{company['role']} _Source: {company['source_title'] or 'company description'}, "
                         f"{harness_format.unlink(company['source_url'])}_")
        return {
            "ok": True,
            "variable": variable,
            "company_role": company,
            "unit": data.get("unit"),
            "cadence": data.get("cadence"),
            "caveat": data.get("caveat"),
            "readings": data.get("readings"),
            "next_reading": data.get("next_reading"),
            "attribution": data.get("attribution"),
            "markdown": markdown,
        }

    # -- save, list, check, seen -----------------------------------------------------------------

    def _harness_save(self, args: dict) -> dict:
        harness = args.get("harness")
        errors, warnings = lint_harness(harness, self._plan_ids)
        if errors:
            return {"ok": False, "error": "invalid_harness", "problems": errors,
                    "message": "Fix these before saving: " + " ".join(errors)}
        store: HarnessStore = self._harness_store_factory()
        harness_id = _text(args, "harness_id")
        if harness_id and store.get(harness_id) is None:
            return self._unknown_harness(harness_id)
        # Ask EquityLayer to read it once before keeping it, so a harness it cannot parse is never stored.
        validated = True
        try:
            self._call("check_thesis_harness", {"harness": harness})
        except McpError as exc:
            if exc.code == "invalid_arguments":
                return {"ok": False, "error": "invalid_harness", "problems": [exc.message],
                        "message": "EquityLayer could not read this harness: " + exc.message}
            validated = False
            warnings.append(f"EquityLayer could not be reached to validate it ({exc.code}). Check it later.")
        target = harness_id or store.unique_id(str(harness.get("title") or harness.get("hypothesis") or "thesis"))
        record, created = store.save_harness(target, harness)
        return {
            "ok": True,
            "harness_id": target,
            "created": created,
            "validated": validated,
            "warnings": warnings,
            "stored_at": str(store.dir / f"{target}.json"),
            "markdown": harness_format.format_saved(record, created, warnings),
        }

    def _harness_list(self, args: dict) -> dict:
        store: HarnessStore = self._harness_store_factory()
        harness_id = _text(args, "harness_id")
        if harness_id:
            record = store.get(harness_id)
            if record is None:
                return self._unknown_harness(harness_id)
            return {"ok": True, "harness_id": harness_id, "record": record,
                    "markdown": harness_format.format_harness(record)}
        records, unreadable = store.all()
        rows = [harness_format.list_row(r, is_due(r)) for r in records]
        return {"ok": True, "count": len(rows), "harnesses": rows, "unreadable": unreadable,
                "markdown": harness_format.format_harness_list(rows, unreadable)}

    def _harness_check(self, args: dict, *, seen: bool = False) -> dict:
        """Check one harness, an inline draft, or every due harness. `seen` is only set by a person's command."""
        inline = args.get("harness")
        if isinstance(inline, dict):
            errors, _ = lint_harness(inline)
            if errors:
                return {"ok": False, "error": "invalid_harness", "problems": errors, "message": " ".join(errors)}
            arguments = {"harness": inline}
            if isinstance(args.get("baseline"), dict):
                arguments["baseline"] = args["baseline"]
            result = self._call("check_thesis_harness", arguments)
            return {**self._check_payload(result), "stored": False,
                    "markdown": harness_format.format_check(result, title=str(inline.get("title") or "draft"))}

        store: HarnessStore = self._harness_store_factory()
        harness_id = _text(args, "harness_id")
        if harness_id:
            record = store.get(harness_id)
            if record is None:
                return self._unknown_harness(harness_id)
            targets, awaiting = [record], []
        else:
            records, _ = store.all()
            # A check nobody has read yet is checked again against the old baseline, so its alert repeats
            # until a person reads it instead of going quiet.
            awaiting = [r for r in records if isinstance(r.get("pending_baseline"), dict)]
            targets = [r for r in records if r in awaiting or is_due(r)]
        mark_seen = seen and not self._in_cron()
        checked, blocks = [], []
        for record in targets:
            try:
                result = self._run_check(store, record, mark_seen)
            except McpError as exc:
                checked.append({"harness_id": record["id"], "ok": False, "error": exc.code, "message": exc.message,
                                "report": True})
                blocks.append(f"**`{record['id']}`:** check failed ({exc.code}). {exc.message} Nothing was changed locally.")
                continue
            report = needs_report(result)
            # Nothing new to read: advancing the baseline loses nothing, so it does not wait for a person.
            saved = mark_seen or not report
            if saved and not mark_seen:
                store.mark_seen(record["id"])
            checked.append({"harness_id": record["id"], **self._check_payload(result), "baseline_saved": saved,
                            "report": report})
            blocks.append(harness_format.format_check(result, harness_id=record["id"],
                                                      title=str(record.get("title") or ""), seen=saved))
        if not blocks:
            blocks.append("No harness is due." if not harness_id else "Nothing to check.")
        needs = sum(len(c.get("needs_human") or []) for c in checked if c.get("ok", True))
        moved = sum(c.get("variables_changed", 0) for c in checked if c.get("ok", True))
        self._refresh_dashboard()
        return {
            "ok": True,
            "mode": "single" if harness_id else "due",
            "checked": checked,
            "needs_human_total": needs,
            "variables_changed_total": moved,
            "errors": sum(1 for c in checked if c.get("ok") is False),
            "report_total": sum(1 for c in checked if c.get("report")),
            "awaiting_read": [c["harness_id"] for c in checked if c.get("report") and not c.get("baseline_saved")],
            "markdown": "\n\n---\n\n".join(blocks),
        }

    def _run_check(self, store: HarnessStore, record: dict, mark_seen: bool) -> dict:
        arguments = {"harness": record["harness"]}
        if isinstance(record.get("baseline"), dict):
            arguments["baseline"] = record["baseline"]
        result = self._call("check_thesis_harness", arguments)
        store.record_check(record["id"], result, seen=mark_seen)
        return result

    @staticmethod
    def _check_payload(result: dict) -> dict:
        changed = result.get("changed") if isinstance(result.get("changed"), dict) else {}
        return {
            "as_of": result.get("as_of"),
            "links": [{"id": l.get("id"), "status": l.get("status"), "reason": l.get("reason")}
                      for l in result.get("links") or [] if isinstance(l, dict)],
            "wrong_if": [{"id": w.get("id"), "result": w.get("result")}
                         for w in result.get("wrong_if") or [] if isinstance(w, dict)],
            "needs_human": result.get("needs_human") or [],
            "variables_changed": len(changed.get("variables") or []),
            "next_due": result.get("next_due"),
            "problems": result.get("problems") or [],
            "boundary": result.get("boundary"),
        }

    def _harness_seen(self, args: dict) -> dict:
        if self._in_cron():
            return dict(CRON_REFUSAL)
        harness_id = _text(args, "harness_id")
        if not harness_id:
            return {"ok": False, "error": "missing_argument", "argument": "harness_id", "message": "Provide harness_id."}
        store: HarnessStore = self._harness_store_factory()
        if store.get(harness_id) is None:
            return self._unknown_harness(harness_id)
        record = store.mark_seen(harness_id)
        if record is None:
            return {"ok": False, "error": "nothing_pending", "harness_id": harness_id,
                    "message": "There is no unread check for this harness."}
        taken = (record.get("baseline") or {}).get("taken_at")
        self._refresh_dashboard()
        return {"ok": True, "harness_id": harness_id, "baseline_taken_at": taken,
                "markdown": f"Marked as read. `{harness_id}` now compares against the check of {taken}."}

    def _harness_remove(self, args: dict) -> dict:
        """Slash command only: the model has no tool that deletes a harness."""
        harness_id = _text(args, "harness_id")
        store: HarnessStore = self._harness_store_factory()
        if not harness_id or not store.delete(harness_id):
            return self._unknown_harness(harness_id)
        self._refresh_dashboard()
        return {"ok": True, "harness_id": harness_id, "markdown": f"Removed `{harness_id}` from this machine."}

    @staticmethod
    def _unknown_harness(harness_id: str) -> dict:
        return {"ok": False, "error": "unknown_harness", "harness_id": harness_id,
                "hint": "Run el_harness_list (/el theses) for saved ids."}
