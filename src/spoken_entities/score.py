"""Score the cached extractions: data/*.jsonl -> docs/results.md. Needs no keys and no audio.

Every extracted value lands in one of three outcomes:
  correct    - equals the true value, and the extractor is sure of it
  re-ask     - missing, marked unsure (even if right), or rejected by the type's validator: the agent asks again
  silent     - wrong, but the validator accepts it and the extractor is sure: the agent acts on it
"""

from __future__ import annotations

import math
import re

from spoken_entities.entities import CHECKSUM, VALIDATORS
from spoken_entities.pipeline import (
    CHANNELS,
    DATA,
    ROOT,
    STYLES,
    _jsonl,
    clips,
    rules_extract,
)

OUTCOMES = ("correct", "re-ask", "silent")


def outcome(etype: str, truth: str, value: str | None, unsure: bool) -> str:
    # An agent re-asks whatever it is unsure of, so a right value marked unsure costs a turn too.
    if value is None or unsure:
        return "re-ask"
    if value == truth:
        return "correct"
    return "silent" if VALIDATORS[etype](value) else "re-ask"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rows() -> list[dict]:
    meta = {c["clip"]: c for c in clips()}
    tr = {(t["clip"], t["voice"], t["channel"]): t["transcript"] for t in _jsonl(DATA / "transcripts.jsonl")}
    # The rules extractor is free, so it runs here on the cached transcripts, never from a cache.
    rules = [{"clip": c, "voice": v, "channel": ch, "extractor": "rules", "unsure": False,
              "value": rules_extract(meta[c]["type"], text)} for (c, v, ch), text in tr.items()]
    out = []
    seen = set()
    for e in rules + [e for e in _jsonl(DATA / "extractions.jsonl") if e["extractor"] != "rules"]:
        key = (e["clip"], e["voice"], e["channel"], e["extractor"])
        if key in seen:  # appended twice: keep the first
            continue
        seen.add(key)
        c = meta[e["clip"]]
        out.append({**e, "type": c["type"], "style": c["style"], "truth": c["value"], "version": c["version"],
                    "transcript": tr.get(key[:3], ""),
                    "outcome": outcome(c["type"], c["value"], e["value"], e.get("unsure", False))})
    return out


def _table(rs: list[dict], by: str, values, extractors) -> list[str]:
    lines = [f"| {by} | extractor | n | correct | re-ask | of which right but unsure | silent wrong (95% CI) |",
             "|---|---|---|---|---|---|---|"]
    for v in values:
        for x in extractors:
            sub = [r for r in rs if r[by] == v and r["extractor"] == x]
            n = len(sub)
            if not n:
                continue
            k = {o: sum(r["outcome"] == o for r in sub) for o in OUTCOMES}
            lo, hi = wilson(k["silent"], n)
            unsure_right = sum(r["value"] == r["truth"] and bool(r.get("unsure")) for r in sub)
            lines.append(f"| {v} | {x} | {n} | {k['correct'] / n:.0%} | {k['re-ask'] / n:.0%} | "
                         f"{unsure_right / n:.0%} | {k['silent'] / n:.1%} ({lo:.1%}–{hi:.1%}) |")
    return lines


FORMAT_ONLY = {"iban": r"IT\d{2}[A-Z]\d{10}[A-Z0-9]{12}",
               "fiscal_code": r"[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]"}


def _without_checksum(rs: list[dict], extractors) -> list[str]:
    lines = ["| extractor | n | wrong values | wrong, sure and format-valid: acted on without the checksum (95% CI) | caught by the checksum |",
             "|---|---|---|---|---|"]
    for x in extractors:
        sub = [r for r in rs if r["extractor"] == x and r["type"] in FORMAT_ONLY]
        wrong = [r for r in sub if r["value"] is not None and r["value"] != r["truth"]]
        passes = [r for r in wrong if re.fullmatch(FORMAT_ONLY[r["type"]], r["value"]) and not r.get("unsure")]
        caught = [r for r in passes if not VALIDATORS[r["type"]](r["value"])]
        if not sub:
            continue
        lo, hi = wilson(len(passes), len(sub))
        lines.append(f"| {x} | {len(sub)} | {len(wrong)} | "
                     f"{len(passes)} = {len(passes) / len(sub):.0%} ({lo:.0%}–{hi:.0%}) | {len(caught)} |")
    return lines


def caught_by(r: dict) -> str:
    """What stopped a wrong value: the extractor's doubt or the validator."""
    if r.get("unsure"):
        return "unsure flag"
    if not VALIDATORS[r["type"]](r["value"]):
        return "checksum" if r["type"] in CHECKSUM else "format"
    return "NOTHING (silent wrong)"


def checksum_overrules(r: dict) -> str:
    """A policy: for a type with a checksum, a value that passes it is accepted even if the extractor
    marked it unsure; everywhere else the extractor's flag decides."""
    if r["type"] in CHECKSUM and r["value"] is not None and VALIDATORS[r["type"]](r["value"]):
        return "correct" if r["value"] == r["truth"] else "silent"
    return r["outcome"]


def _policy_table(rs: list[dict], extractors) -> list[str]:
    lines = ["| extractor | policy | correct | re-ask | silent wrong |", "|---|---|---|---|---|"]
    for x in extractors:
        sub = [r for r in rs if r["extractor"] == x]
        for name, f in (("the extractor's flag decides", lambda r: r["outcome"]),
                        ("the checksum overrules 'unsure'", checksum_overrules)):
            k = {o: sum(f(r) == o for r in sub) for o in OUTCOMES}
            lines.append(f"| {x} | {name} | {k['correct']} | {k['re-ask']} | {k['silent']} |")
    return lines


def current(rs: list[dict]) -> list[dict]:
    """The set the headline tables use: v2 IBANs and fiscal codes, every other type as is."""
    return [r for r in rs if r["version"] == "v2" or r["type"] not in CHECKSUM]


def report(all_rs: list[dict]) -> str:
    extractors = sorted({r["extractor"] for r in all_rs}, key=lambda x: (x != "rules", x))
    for r in all_rs:
        r["validator"] = "checksum" if r["type"] in CHECKSUM else "format only"
    rs = current(all_rs)
    long_codes = [r for r in all_rs if r["type"] in CHECKSUM]
    out = ["# Results", "",
           "Generated by `python -m spoken_entities.score` from the cached transcripts and extractions in `data/`.",
           "Do not edit by hand.", "",
           f"{len({r['clip'] for r in rs})} clips × {len({r['voice'] for r in rs})} voices × "
           f"{len({r['channel'] for r in rs})} channels, per extractor. "
           "**silent wrong** = a wrong value the validator accepts and the extractor is sure of: "
           "the agent acts on it.", "",
           "## By channel", "", *_table(rs, "channel", CHANNELS, extractors), "",
           "## By validator", "",
           "A checksum (IBAN, codice fiscale) rejects most wrong values, so they become re-asks; "
           "a format check does not.", "",
           *_table(rs, "validator", ("checksum", "format only"), extractors), "",
           "## Without the checksum", "",
           "The same IBANs and fiscal codes, if the only check were the format: how many wrong values "
           "would the agent act on? A value the extractor marked unsure is still a re-ask.", "",
           *_without_checksum(rs, extractors), "",
           "## Letting the checksum overrule 'unsure'", "",
           f"Counts over all {len(rs) // max(1, len(extractors))} recordings per extractor. A value marked unsure is a re-ask "
           "in every other table; here, for IBANs and fiscal codes, a value that passes the checksum is "
           "accepted anyway.", "",
           *_policy_table(rs, extractors), "",
           "## v1 against v2 long codes", "",
           "v1 IBANs carried ten nines in a row and v1 fiscal codes the place code Y999, to make them "
           "unassignable; v2 uses realistic patterns (a wrong national check letter in the IBAN, a day "
           "of birth of 32-40 in the fiscal code). Every other table uses v2.", "",
           *_table(long_codes, "version", ("v1", "v2"), extractors), "",
           "Without the checksum, v1:", "", *_without_checksum([r for r in long_codes if r["version"] == "v1"], extractors), "",
           "## By how the caller said it", "", *_table(rs, "style", STYLES, extractors), "",
           "## By entity type", "", *_table(rs, "type", sorted({r["type"] for r in rs}), extractors), "",
           "## Every wrong value and what caught it", "",
           "Values that came out and were wrong (missing values are not listed). A silent wrong value "
           "would show NOTHING in the last column.", "",
           "| extractor | type | values | style | channel | voice | true | extracted | caught by |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted((r for r in all_rs if r["value"] is not None and r["value"] != r["truth"]),
                    key=lambda r: (extractors.index(r["extractor"]), r["type"], r["clip"], r["voice"],
                                   CHANNELS.index(r["channel"]))):
        out.append(f"| {r['extractor']} | {r['type']} | {r['version']} | {r['style']} | {r['channel']} | {r['voice']} | "
                   f"`{r['truth']}` | `{r['value']}` | {caught_by(r)} |")
    return "\n".join(out) + "\n"


def main() -> None:
    path = ROOT / "docs" / "results.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(report(rows()), encoding="utf-8", newline="\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
