"""
Letter Explainer - core logic (Python standard library only).

Pipeline:
  1. check_input()   - reject empty / too-short / non-letter input BEFORE spending an AI call
  2. explain()       - ask Claude for a structured JSON explanation
                       (or a rule-based fallback when no API key is set: "offline demo mode")
  3. verify()        - the anti-hallucination step: every date and dollar amount the AI
                       reports must literally appear in the original letter. Anything that
                       doesn't is flagged so the user knows not to trust it blindly.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal, InvalidOperation

MODEL = os.environ.get("LETTER_MODEL", "claude-sonnet-5-5")
MIN_CHARS = 80
MAX_CHARS = 20_000

# --------------------------------------------------------------------------- #
# 1. Input checks
# --------------------------------------------------------------------------- #

OFFICIAL_HINTS = [
    "notice", "department", "dmv", "irs", "franchise tax", "ftb", "county", "state of",
    "due", "penalty", "deadline", "renew", "registration", "taxpayer", "account",
    "assessor", "treasurer", "court", "agency", "pay by", "respond by",
]


def check_input(text: str) -> tuple[bool, str]:
    """Cheap pre-check. Returns (ok, message)."""
    stripped = (text or "").strip()
    if not stripped:
        return False, "The letter is empty. Paste the full text of the letter you received."
    if len(stripped) < MIN_CHARS:
        return False, (
            f"That's only {len(stripped)} characters - too short to be a full letter. "
            "Paste the whole letter, including dates and amounts."
        )
    if len(stripped) > MAX_CHARS:
        return False, (
            f"That's {len(stripped):,} characters - longer than a typical letter. "
            f"Paste only the main pages (up to {MAX_CHARS:,} characters)."
        )
    return True, ""


def looks_official(text: str) -> bool:
    low = text.lower()
    return sum(1 for h in OFFICIAL_HINTS if h in low) >= 2


# --------------------------------------------------------------------------- #
# 2. Extracting dates and money from raw text (used by verifier + fallback)
# --------------------------------------------------------------------------- #

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_PATTERNS = [
    # March 3, 2026 / Mar. 3 2026
    (re.compile(_MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I), "mdy_name"),
    # 3 March 2026
    (re.compile(r"(\d{1,2})\s+" + _MONTH_RE + r"\.?,?\s+(\d{4})", re.I), "dmy_name"),
    # 03/03/2026 or 3-3-2026
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"), "mdy_num"),
    # 2026-03-03
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
]
MONEY_RE = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[tuple[date, str]]:
    """Return (parsed_date, original_snippet) for every date found in text."""
    out: list[tuple[date, str]] = []
    for pat, kind in DATE_PATTERNS:
        for m in pat.finditer(text or ""):
            g = m.groups()
            if kind == "mdy_name":
                d = _safe_date(int(g[2]), MONTHS[g[0].lower()[:3]], int(g[1]))
            elif kind == "dmy_name":
                d = _safe_date(int(g[2]), MONTHS[g[1].lower()[:3]], int(g[0]))
            elif kind == "mdy_num":
                d = _safe_date(int(g[2]), int(g[0]), int(g[1]))
            else:
                d = _safe_date(int(g[0]), int(g[1]), int(g[2]))
            if d:
                out.append((d, m.group(0)))
    return out


def parse_one_date(s: str) -> date | None:
    found = find_dates(s or "")
    return found[0][0] if found else None


def find_amounts(text: str) -> list[tuple[Decimal, str]]:
    out = []
    for m in MONEY_RE.finditer(text or ""):
        whole = m.group(1).replace(",", "")
        cents = m.group(2) or "00"
        try:
            out.append((Decimal(f"{whole}.{cents}"), re.sub(r"\s+", "", m.group(0))))
        except InvalidOperation:
            pass
    return out


def parse_one_amount(s) -> Decimal | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return Decimal(str(s)).quantize(Decimal("0.01"))
    found = find_amounts(str(s))
    if found:
        return found[0][0]
    try:  # AI sometimes returns "1234.50" without a $
        return Decimal(str(s).replace(",", "").strip()).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


# --------------------------------------------------------------------------- #
# 3. The AI step
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """You help ordinary people understand official letters (DMV, IRS, California FTB, county tax bills, courts, utilities).
Read the letter and reply with ONLY a JSON object, no prose, using exactly this shape:

{
  "is_official_letter": true/false,          // false for receipts, ads, personal mail, random text
  "language": "English",                     // language the letter is written in
  "sender": "who sent it",
  "summary": "2-4 sentences, plain English, 6th-grade reading level. What is this and why did I get it?",
  "deadlines": [
    {"date": "copy the date EXACTLY as written in the letter", "what": "what must happen by then"}
  ],
  "amounts": [
    {"amount": "copy the dollar amount EXACTLY as written in the letter", "what": "what this money is for"}
  ],
  "amount_due_now": "the single amount the reader must pay, copied exactly as written, or null if none",
  "next_steps": ["short imperative checklist item", "..."],
  "warnings": ["anything confusing, ambiguous, or that the reader should double-check with the agency"]
}

Rules:
- Only use dates and dollar amounts that are printed in the letter. Copy them character-for-character. Never calculate, add up, or estimate new numbers.
- If something is unclear, say so in "warnings" instead of guessing.
- If is_official_letter is false, leave deadlines/amounts empty and explain in "summary" what the text appears to be.
- Do not give legal or tax advice; suggest contacting the agency or a professional when the stakes are high."""


class AIError(Exception):
    pass


def call_claude(letter: str, api_key: str) -> dict:
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 1500,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": f"<letter>\n{letter}\n</letter>"}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise AIError(f"API error {e.code}: {e.read().decode()[:300]}") from e
    except urllib.error.URLError as e:
        raise AIError(f"Could not reach the API: {e.reason}") from e

    text = "".join(b.get("text", "") for b in data.get("content", []))
    return parse_json_reply(text)


def parse_json_reply(text: str) -> dict:
    """Pull the JSON object out of the model reply, tolerating ``` fences."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AIError("The AI reply did not contain JSON.")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise AIError(f"The AI reply was not valid JSON: {e}") from e


# --------------------------------------------------------------------------- #
# Offline demo mode (no API key) - rule-based, clearly labeled in the UI
# --------------------------------------------------------------------------- #

DEADLINE_WORDS = re.compile(r"\b(by|before|no later than|due|deadline|expires?|on or before|within)\b", re.I)


def deadline_dates(text: str, lookback: int = 60) -> list[tuple[date, str]]:
    """
    Dates that have a deadline word ("by", "due", "no later than"...) shortly before them.
    Line breaks are collapsed first, because letters often wrap mid-sentence
    ("postmarked no later than\\nNovember 21, 2026") - splitting by line missed those.
    """
    flat = re.sub(r"\s+", " ", text or "")
    out = []
    for pat, _ in DATE_PATTERNS:
        for m in pat.finditer(flat):
            window = flat[max(0, m.start() - lookback):m.start()]
            if DEADLINE_WORDS.search(window):
                d = parse_one_date(m.group(0))
                if d and d not in [x for x, _ in out]:
                    out.append((d, m.group(0)))
    return out


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def rule_based_explain(letter: str) -> dict:
    official = looks_official(letter)
    sents = _sentences(letter)
    flat = re.sub(r"\s+", " ", letter)
    deadlines, amounts, seen_a = [], [], set()
    for d, raw in deadline_dates(letter):
        i = flat.find(raw)
        context = flat[max(0, i - 100): i + len(raw)].strip()
        deadlines.append({"date": raw, "what": "…" + context})
    for s in sents:
        for a, raw in find_amounts(s):
            if a not in seen_a:
                seen_a.add(a)
                amounts.append({"amount": raw, "what": s[:160]})
    due = None
    for s in sents:
        if re.search(r"(amount due|total due|balance due|pay this amount|total amount)", s, re.I):
            f = find_amounts(s)
            if f:
                due = f[-1][1]
                break
    return {
        "is_official_letter": official,
        "language": "unknown (offline mode)",
        "sender": next((s[:80] for s in sents if not s.startswith("[")), ""),
        "summary": ("Offline demo mode: no AI was used. Below are the dates and dollar amounts found "
                    "near deadline words. Set ANTHROPIC_API_KEY for a plain-English explanation.")
                   if official else "Offline demo mode: this does not look like an official letter.",
        "deadlines": deadlines if official else [],
        "amounts": amounts if official else [],
        "amount_due_now": due if official else None,
        "next_steps": ["Read each deadline below and put it on your calendar."] if official else [],
        "warnings": ["Rule-based extraction only - sentences are quoted, not explained."],
    }


# --------------------------------------------------------------------------- #
# 4. Verification - the "catch a plausible but wrong answer" step
# --------------------------------------------------------------------------- #

def verify(result: dict, letter: str) -> dict:
    """
    Mark each deadline/amount as verified (appears in the letter) or not.
    Comparison is by VALUE, not exact string, so "$1,204.50" in the AI output
    matches "$1204.50" in the letter, and "03/15/2027" matches "March 15, 2027".
    """
    letter_dates = {d for d, _ in find_dates(letter)}
    letter_amounts = {a for a, _ in find_amounts(letter)}
    issues = []

    for item in result.get("deadlines", []) or []:
        d = parse_one_date(str(item.get("date", "")))
        item["verified"] = bool(d and d in letter_dates)
        if not item["verified"]:
            issues.append(f"Deadline \"{item.get('date')}\" was not found in the letter.")

    for item in result.get("amounts", []) or []:
        a = parse_one_amount(item.get("amount"))
        item["verified"] = bool(a is not None and a in letter_amounts)
        if not item["verified"]:
            issues.append(f"Amount \"{item.get('amount')}\" was not found in the letter "
                          "(it may have been calculated or misread).")

    due = result.get("amount_due_now")
    if due not in (None, "", "null"):
        a = parse_one_amount(due)
        result["amount_due_verified"] = bool(a is not None and a in letter_amounts)
        if not result["amount_due_verified"]:
            issues.append(f"Amount due \"{due}\" was not found in the letter.")
    else:
        result["amount_due_verified"] = None

    # Coverage check: did the AI miss a date that sits next to a deadline word?
    reported = {parse_one_date(str(i.get("date", ""))) for i in result.get("deadlines", []) or []}
    missed = []
    for d, raw in deadline_dates(letter):
        if d not in reported and raw not in missed:
            missed.append(raw)
    result["possibly_missed_dates"] = missed if result.get("is_official_letter") else []
    if result["possibly_missed_dates"]:
        issues.append("Possible deadlines in the letter the explanation didn't list: "
                      + ", ".join(missed))

    result["verification_issues"] = issues
    result["all_verified"] = not issues
    return result


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def explain(letter: str, api_key: str | None = None) -> dict:
    ok, msg = check_input(letter)
    if not ok:
        return {"error": msg}
    api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            result = call_claude(letter, api_key)
            result["mode"] = "ai"
        except AIError as e:
            return {"error": str(e)}
    else:
        result = rule_based_explain(letter)
        result["mode"] = "offline"
    return verify(result, letter)
