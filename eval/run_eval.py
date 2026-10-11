"""
Eval runner for the code reviewer.

Runs every file in REVIEW_FILES with use_retrieval=False and use_retrieval=True,
scores the findings against the planted issues in library_app, and prints a
comparison table. Raw results and a report are saved to ./eval_results/.

Setup:
    pip install requests
    PowerShell:  $env:EVAL_TOKEN="<your login token>"
                 # or: $env:EVAL_EMAIL="you@example.com"; $env:EVAL_PASSWORD="..."
    Run:         python eval/run_eval.py --project 3 --path-prefix library_app/ --label my-model
    No server?   python eval/run_eval.py --selftest

Useful flags:
    --runs 3             repeat each cell 3 times (LLM output varies run to run)
    --only src/library.cpp   run just one file
    --delay 8            seconds to wait between calls (free-tier friendly)
    --base http://localhost:8000
    --email / --password login instead of pasting a token
    --model-id ID        model selection id (builtin name or custom:N)
    --path-prefix PFX    prepend to REVIEW_FILES paths in the request only

Scoring is keyword + line-number matching, so it is a good first pass but not a
judge. Always read the UNMATCHED findings it prints: some will be real bugs the
key doesn't list, and some may be correct findings the keywords missed.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Wired to our FastAPI shapes (ProjectReviewRequest / ProjectReviewResponse)
# ---------------------------------------------------------------------------
# POST /projects/{project_id}/review
REVIEW_PATH = "/projects/{project_id}/review"
LOGIN_PATH = "/auth/login"


def build_body(file_path, use_retrieval, model_id=None):
    # Bare use_retrieval=false returns empty panels. OFF mode sets
    # compare_without_rag so without_retrieval is populated (see projects.py).
    body = {
        "file_path": file_path,
        "use_retrieval": use_retrieval,
        "compare_without_rag": not use_retrieval,
    }
    if model_id:
        body["model"] = model_id
    return body


def extract_findings(resp_json):
    # ProjectReviewResponse: with_retrieval | without_retrieval -> review.findings
    if not isinstance(resp_json, dict):
        return []
    for key in ("with_retrieval", "without_retrieval"):
        panel = resp_json.get(key)
        if isinstance(panel, dict) and isinstance(panel.get("review"), dict):
            return panel["review"].get("findings") or []
    if "findings" in resp_json:
        return resp_json["findings"] or []
    if isinstance(resp_json.get("review"), dict):
        return resp_json["review"].get("findings") or []
    return []


def extract_model_meta(resp_json):
    """Model name from the panel that produced the review (StoredReviewOut.model)."""
    if not isinstance(resp_json, dict):
        return {}
    for key in ("with_retrieval", "without_retrieval"):
        panel = resp_json.get(key)
        if isinstance(panel, dict) and panel.get("model"):
            return {
                "model": panel.get("model"),
                "retrieval_enabled": panel.get("retrieval_enabled"),
            }
    return {}


# Field names inside each Finding (app.schemas.Finding)
F_LOCATION, F_ISSUE, F_SUGGESTION = "location", "issue", "suggestion"

# ---------------------------------------------------------------------------
# The planted issues (mirrors answer_key.json). Keep this file OUT of the repo
# you upload to the reviewer.
# ---------------------------------------------------------------------------
REVIEW_FILES = [
    "src/library.cpp", "src/main.cpp", "src/utils.cpp",
    "src/book.cpp", "src/member.cpp", "src/report.cpp",
]
CLEAN_FILES = {"src/report.cpp"}

# groups: a finding matches if ALL words in ANY one group appear in its text
ISSUES = {
    "X1": dict(kind="cross", file="src/library.cpp", line=80,
               desc="calculateFine args swapped (fine always 0)",
               groups=[["calculatefine", "swap"], ["calculatefine", "order"],
                       ["calculatefine", "argument"], ["calculatefine", "parameter"],
                       ["rateperday", "daysoverdue"], ["fine", "always", "zero"]]),
    "X2": dict(kind="cross", file="src/main.cpp", line=28,
               desc="findBook() result dereferenced without null check",
               groups=[["findbook", "null"], ["nullptr", "dereference"],
                       ["missing", "null"], ["null", "check"], ["null", "pointer"]]),
    "X3": dict(kind="cross", file="src/library.cpp", line=66,
               desc="borrow limit off-by-one (> instead of >=)",
               groups=[["off-by-one"], ["off by one"],
                       ["borrowedcount", "borrowlimit", ">="],
                       ["borrowedcount", "borrowlimit", "exceed"],
                       ["borrowedcount", "borrowlimit", "more than"],
                       ["borrowlimit", "one more"]]),
    "X4": dict(kind="cross", file="src/library.cpp", line=76,
               desc="returnBook never marks the book available again",
               groups=[["setavailable", "return"], ["available", "returnbook"],
                       ["not marked available"], ["never", "available"],
                       ["stays unavailable"], ["remain", "unavailable"],
                       ["remains", "on loan"], ["still", "on loan"]]),
    "X5": dict(kind="cross", file="src/library.cpp", line=45,
               desc="registerMember skips isValidMemberId",
               groups=[["isvalidmemberid"], ["member id", "validat"],
                       ["memberid", "validat"], ["validate", "member"]]),
    "S1": dict(kind="single", file="src/utils.cpp", line=52,
               desc="formatIsbn strcpy overflows char[13]",
               groups=[["strcpy"], ["buffer overflow"], ["digits[13]"],
                       ["null terminator"], ["nul terminator"], ["buffer", "too small"]]),
    "S2": dict(kind="single", file="src/book.cpp", line=23,
               desc="averageRating divides by zero on no ratings",
               groups=[["division by zero"], ["divide by zero"], ["divides by zero"],
                       ["empty", "ratings"], ["integer division"], ["size()", "zero"]]),
    "S3": dict(kind="single", file="src/member.cpp", line=8,
               desc="borrowedCount_ never initialized",
               groups=[["uninitialized"], ["uninitialised"], ["not initialized"],
                       ["borrowedcount_", "initializ"], ["indeterminate"]]),
    "S4": dict(kind="single", file="src/library.cpp", line=21,
               desc="removeBook uses iterator after erase",
               groups=[["iterator", "invalid"], ["erase", "iterator"],
                       ["erase", "loop"], ["after erase"], ["undefined behavior", "erase"]]),
    "S5": dict(kind="single", file="src/library.cpp", line=13,
               desc="raw new Book never freed (leak)",
               groups=[["destructor"], ["raw pointer"], ["owning"], ["new book"], ["addbook", "leak"]]),
}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def finding_text(f):
    return " ".join(str(f.get(k, "")) for k in (F_LOCATION, F_ISSUE, F_SUGGESTION)).lower()


def parse_line_refs(finding):
    """Pull (start, end) line references out of the location (and 'line N' in text)."""
    loc = str(finding.get(F_LOCATION, "")).lower()
    text = finding_text(finding)
    refs = []
    for m in re.finditer(r"(\d+)\s*(?:-|\u2013|to)\s*(\d+)", loc):
        a, b = int(m.group(1)), int(m.group(2))
        if a <= b < 5000:
            refs.append((a, b))
    for m in re.finditer(r"\blines?\s*(\d+)", text):
        n = int(m.group(1))
        refs.append((n, n))
    if re.fullmatch(r"\s*\d+\s*", loc):
        n = int(loc)
        refs.append((n, n))
    return refs


def line_near(refs, key_line, tol=5):
    return any(a - tol <= key_line <= b + tol for a, b in refs)


def assign(finding, file_path):
    """Credit a finding to at most one planted issue (the best keyword/line match)."""
    text = finding_text(finding)
    refs = parse_line_refs(finding)
    best, best_score = None, 0
    for iid, iss in ISSUES.items():
        if iss["file"] != file_path:
            continue
        kw = sum(1 for g in iss["groups"] if all(w in text for w in g))
        if kw == 0:
            continue
        score = kw * 2 + (3 if line_near(refs, iss["line"]) else 0)
        if score > best_score:
            best, best_score = iid, score
    return best


def score_mode(runs_by_file):
    """runs_by_file: {file: [list_of_findings_per_run, ...]} -> stats dict."""
    hits = {iid: 0 for iid in ISSUES}
    n_runs = {iid: len(runs_by_file.get(iss["file"], [])) for iid, iss in ISSUES.items()}
    unmatched, total, clean_findings = [], 0, 0
    for file_path, runs in runs_by_file.items():
        for findings in runs:
            matched_here = set()
            for f in findings:
                total += 1
                iid = assign(f, file_path)
                if iid:
                    matched_here.add(iid)
                else:
                    unmatched.append((file_path, f))
                    if file_path in CLEAN_FILES:
                        clean_findings += 1
            for iid in matched_here:
                hits[iid] += 1
    rates = {iid: (hits[iid] / n_runs[iid] if n_runs[iid] else None) for iid in ISSUES}

    def recall(kind):
        vals = [r for iid, r in rates.items() if ISSUES[iid]["kind"] == kind and r is not None]
        return sum(vals) / len(vals) if vals else None

    return dict(rates=rates, cross_recall=recall("cross"), single_recall=recall("single"),
                total_findings=total, unmatched=unmatched, clean_findings=clean_findings)


def pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"


def build_report(label, results, errors):
    off, on = score_mode(results["off"]), score_mode(results["on"])
    lines = [f"# Eval report: {label}", f"Generated {datetime.now():%Y-%m-%d %H:%M}", ""]
    lines += ["## Summary", "",
              "| Metric | Retrieval OFF | Retrieval ON |", "|---|---|---|",
              f"| Cross-file recall (X1-X5) | {pct(off['cross_recall'])} | {pct(on['cross_recall'])} |",
              f"| Single-file recall (S1-S5) | {pct(off['single_recall'])} | {pct(on['single_recall'])} |",
              f"| Total findings | {off['total_findings']} | {on['total_findings']} |",
              f"| Unmatched findings (check by hand) | {len(off['unmatched'])} | {len(on['unmatched'])} |",
              f"| Findings on clean file (report.cpp) | {off['clean_findings']} | {on['clean_findings']} |",
              "", "## Per issue (share of runs that found it)", "",
              "| ID | Issue | OFF | ON |", "|---|---|---|---|"]
    for iid, iss in ISSUES.items():
        lines.append(f"| {iid} | {iss['desc']} | {pct(off['rates'][iid])} | {pct(on['rates'][iid])} |")
    for name, st in (("OFF", off), ("ON", on)):
        lines += ["", f"## Unmatched findings, retrieval {name}",
                  "Real bugs the key does not list, wrong findings, or hits the keywords missed. Judge by hand.", ""]
        if not st["unmatched"]:
            lines.append("(none)")
        for file_path, f in st["unmatched"]:
            lines.append(f"- `{file_path}` [{f.get(F_LOCATION, '?')}] {str(f.get(F_ISSUE, ''))[:160]}")
    if errors:
        lines += ["", "## Errors (these cells have no data)", ""]
        lines += [f"- {e}" for e in errors]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def resolve_token(args):
    """EVAL_TOKEN / --token wins; otherwise POST /auth/login."""
    token = args.token or os.environ.get("EVAL_TOKEN")
    if token:
        return token
    email = args.email or os.environ.get("EVAL_EMAIL")
    password = args.password or os.environ.get("EVAL_PASSWORD")
    if not email or not password:
        sys.exit("Set EVAL_TOKEN, or provide --email/--password (or EVAL_EMAIL / EVAL_PASSWORD).")
    url = args.base.rstrip("/") + LOGIN_PATH
    try:
        r = requests.post(url, json={"email": email, "password": password}, timeout=30)
    except requests.RequestException as e:
        sys.exit(f"Login request failed: {e}")
    if r.status_code != 200:
        sys.exit(f"Login failed (HTTP {r.status_code}).")
    token = (r.json() or {}).get("access_token")
    if not token:
        sys.exit("Login response did not include access_token.")
    return token


def call_review(base, token, project_id, file_path, use_retrieval, timeout, model_id=None):
    url = base.rstrip("/") + REVIEW_PATH.format(project_id=project_id)
    headers = {"Authorization": f"Bearer {token}"}
    err = "unknown error"
    for attempt in range(5):
        try:
            r = requests.post(
                url,
                json=build_body(file_path, use_retrieval, model_id=model_id),
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as e:
            err = f"network error: {e}"
        else:
            if r.status_code == 200:
                body = r.json()
                return extract_findings(body), None, extract_model_meta(body)
            err = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code not in (429, 500, 502, 503, 504):
                return None, err, {}
        wait = 5 * 2 ** attempt
        print(f"    retry in {wait}s ({err})")
        time.sleep(wait)
    return None, err, {}


def run_eval(args):
    token = resolve_token(args)
    files = [args.only] if args.only else REVIEW_FILES
    results = {"off": {f: [] for f in files}, "on": {f: [] for f in files}}
    errors = []
    models_seen = []
    prefix = (args.path_prefix or "").strip()
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    if args.model_id:
        print(f"Model selection id: {args.model_id}")
    total_calls = len(files) * 2 * args.runs
    done = 0
    for file_path in files:
        request_path = f"{prefix}{file_path}" if prefix else file_path
        for mode, flag in (("off", False), ("on", True)):
            for i in range(args.runs):
                done += 1
                print(f"[{done}/{total_calls}] {file_path} retrieval={'ON' if flag else 'OFF'} run {i + 1}")
                if request_path != file_path:
                    print(f"    request path: {request_path}")
                findings, err, meta = call_review(
                    args.base, token, args.project, request_path, flag, args.timeout,
                    model_id=args.model_id,
                )
                if err:
                    errors.append(f"{file_path} retrieval={mode} run {i + 1}: {err}")
                    print(f"    FAILED: {err}")
                else:
                    results[mode][file_path].append(findings)
                    if meta:
                        models_seen.append(meta)
                        print(f"    {len(findings)} findings (model={meta.get('model', '?')})")
                    else:
                        print(f"    {len(findings)} findings")
                time.sleep(args.delay)
    save_and_print(args.label, results, errors, args.out_dir, meta={
        "model_id": args.model_id,
        "path_prefix": prefix or None,
        "models_from_response": models_seen,
    })


def save_and_print(label, results, errors, out_dir, meta=None):
    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", label)
    payload = dict(results)
    if meta:
        payload["_meta"] = meta
    (out / f"raw_{safe}_{stamp}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    report = build_report(label, results, errors)
    (out / f"report_{safe}_{stamp}.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\nSaved to {out}/ (raw_{safe}_{stamp}.json and report_{safe}_{stamp}.md)")


# ---------------------------------------------------------------------------
# Self-test: checks the scoring logic with fake findings, no server needed
# ---------------------------------------------------------------------------
def selftest():
    fake_off = {
        "src/library.cpp": [[
            {"location": "lines 66", "issue": "borrowedCount compared with borrowLimit using > is an off-by-one", "suggestion": "use >="},
            {"location": "removeBook, lines 17-27", "issue": "Iterator is invalidated after erase inside the loop", "suggestion": "use erase's return value"},
            {"location": "line 13", "issue": "new Book is never deleted, memory leak", "suggestion": "use unique_ptr"},
            {"location": "line 30", "issue": "Function is a bit long", "suggestion": "split it"},
        ]],
        "src/report.cpp": [[{"location": "line 9", "issue": "Magic number 72", "suggestion": "name it"}]],
    }
    fake_on = {
        "src/library.cpp": [[
            {"location": "line 80", "issue": "Arguments to calculateFine are swapped; fine is always zero", "suggestion": "swap them"},
            {"location": "returnBook 76-90", "issue": "returnBook never calls setAvailable(true) so the book stays on loan", "suggestion": "call it"},
            {"location": "line 37", "issue": "registerMember never calls isValidMemberId", "suggestion": "validate"},
        ]],
        "src/main.cpp": [[{"location": "line 28", "issue": "findBook may return nullptr; dereference without null check", "suggestion": "check"}]],
        "src/report.cpp": [[]],
    }
    report = build_report("selftest", {"off": fake_off, "on": fake_on}, [])
    print(report)
    off, on = score_mode(fake_off), score_mode(fake_on)
    assert off["rates"]["X3"] == 1.0 and off["rates"]["S4"] == 1.0 and off["rates"]["S5"] == 1.0
    assert off["rates"]["X1"] == 0.0, "X1 should be missed with retrieval off"
    assert on["rates"]["X1"] == 1.0 and on["rates"]["X2"] == 1.0
    assert on["rates"]["X4"] == 1.0 and on["rates"]["X5"] == 1.0
    assert off["clean_findings"] == 1 and on["clean_findings"] == 0
    print("\nSELFTEST PASSED")


def main():
    p = argparse.ArgumentParser(description="Run the reviewer eval")
    p.add_argument("--project", type=int, help="project id of the uploaded library_app")
    p.add_argument("--label", default="run", help="name for this run, e.g. the model used")
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--delay", type=float, default=6.0)
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--only", help="run a single file, e.g. src/library.cpp")
    p.add_argument("--out-dir", default="eval_results")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--token", help="Bearer token (overrides EVAL_TOKEN)")
    p.add_argument("--email", help="login email (or EVAL_EMAIL)")
    p.add_argument("--password", help="login password (or EVAL_PASSWORD); never printed")
    p.add_argument("--model-id", help="passed as body.model (builtin id or custom:N)")
    p.add_argument(
        "--path-prefix",
        help="prefix for request paths only, e.g. library_app/ (scoring keys stay src/...)",
    )
    args = p.parse_args()
    if args.selftest:
        selftest()
        return
    if args.project is None:
        p.error("--project is required")
    run_eval(args)


if __name__ == "__main__":
    main()