#!/usr/bin/env python3
"""Harness CLI: feature lock, session logs, status.

    python scripts/harness.py check                  validate + lock integrity (CI gate)
    python scripts/harness.py status                 what is done, in progress, next
    python scripts/harness.py next                   the single next actionable feature
    python scripts/harness.py show F-011             one feature in full
    python scripts/harness.py start F-011            mark in_progress, open a session log
    python scripts/harness.py verify F-011           run that feature's verify command
    python scripts/harness.py done F-011             mark done (refuses if verify fails)
    python scripts/harness.py session-new "title"    open a session log without a feature
    python scripts/harness.py relock                 recompute the lock hash (needs a changelog entry)

Why a lock at all: a backlog that can be edited silently is not a plan, it is a mood. The
hash covers only the fields that define what a feature *is* -- id, title, why, acceptance,
verify, dependencies. Status and session references move freely. Changing a locked field
without bumping lock_version and writing a changelog entry fails `check`, and therefore CI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "harness" / "features.json"
SCHEMA = ROOT / "harness" / "feature_schema.json"
LOCK = ROOT / "harness" / "features.lock"
SESSIONS = ROOT / "harness" / "sessions"
PROGRESS = ROOT / "harness" / "PROGRESS.md"

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


# --------------------------------------------------------------------------- load

def load() -> dict:
    return json.loads(FEATURES.read_text())


def save(data: dict) -> None:
    FEATURES.write_text(json.dumps(data, indent=2) + "\n")


def features_by_id(data: dict) -> dict:
    return {f["id"]: f for f in data["features"]}


# --------------------------------------------------------------------------- lock

def lock_payload(data: dict) -> str:
    """Canonical serialisation of everything the lock protects.

    Deliberately excludes mutable fields, so ordinary progress does not churn the hash.
    """
    locked = data["locked_fields"]
    body = [{k: f[k] for k in locked if k in f} for f in data["features"]]
    return json.dumps({"lock_version": data["lock_version"], "features": body},
                      sort_keys=True, separators=(",", ":"))


def lock_hash(data: dict) -> str:
    return hashlib.sha256(lock_payload(data).encode()).hexdigest()


def read_lock() -> dict | None:
    if not LOCK.exists():
        return None
    return json.loads(LOCK.read_text())


def write_lock(data: dict) -> dict:
    payload = {"lock_version": data["lock_version"], "sha256": lock_hash(data),
               "n_features": len(data["features"]), "written": str(date.today())}
    LOCK.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


# --------------------------------------------------------------------------- validate

def validate(data: dict) -> list[str]:
    """Schema-shaped validation plus the invariants a JSON Schema cannot express."""
    errors: list[str] = []
    schema = json.loads(SCHEMA.read_text())
    props = schema["properties"]["features"]["items"]
    required = set(props["required"])
    allowed = set(props["properties"])
    statuses = set(props["properties"]["status"]["enum"])
    areas = set(props["properties"]["area"]["enum"])

    ids: list[str] = []
    for f in data["features"]:
        fid = f.get("id", "<no id>")
        missing = required - set(f)
        if missing:
            errors.append(f"{fid}: missing required fields {sorted(missing)}")
        extra = set(f) - allowed
        if extra:
            errors.append(f"{fid}: unknown fields {sorted(extra)}")
        if not re.fullmatch(r"F-\d{3}", fid):
            errors.append(f"{fid}: id must match F-NNN")
        if f.get("status") not in statuses:
            errors.append(f"{fid}: bad status {f.get('status')!r}")
        if f.get("area") not in areas:
            errors.append(f"{fid}: bad area {f.get('area')!r}")
        if len(f.get("acceptance", [])) < 2:
            errors.append(f"{fid}: needs at least two acceptance criteria")
        if len(f.get("why", "")) < 40:
            errors.append(f"{fid}: 'why' is too thin to be a rationale")
        if not f.get("verify"):
            errors.append(f"{fid}: no verify command -- human review is not a gate")
        if f.get("status") == "done" and not f.get("sessions"):
            errors.append(f"{fid}: done but no session log references it")
        if f.get("status") == "blocked" and not f.get("blocked_reason"):
            errors.append(f"{fid}: blocked without a stated reason")
        ids.append(fid)

    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append(f"duplicate ids: {sorted(dupes)}")

    known = set(ids)
    for f in data["features"]:
        for dep in f.get("depends_on", []):
            if dep not in known:
                errors.append(f"{f['id']}: depends on unknown {dep}")
            elif dep == f["id"]:
                errors.append(f"{f['id']}: depends on itself")

    # A done feature standing on an unfinished dependency means the ledger is lying.
    by_id = features_by_id(data)
    for f in data["features"]:
        if f["status"] != "done":
            continue
        for dep in f.get("depends_on", []):
            if dep in by_id and by_id[dep]["status"] not in ("done", "dropped"):
                errors.append(f"{f['id']}: done but dependency {dep} is "
                              f"{by_id[dep]['status']}")

    in_progress = [f["id"] for f in data["features"] if f["status"] == "in_progress"]
    if len(in_progress) > 1:
        errors.append(f"policy one_at_a_time violated: {in_progress}")

    if _cycle(by_id):
        errors.append(f"dependency cycle involving {_cycle(by_id)}")

    latest = max(c["lock_version"] for c in data["changelog"])
    if latest != data["lock_version"]:
        errors.append(f"lock_version {data['lock_version']} has no changelog entry "
                      f"(latest entry is v{latest})")
    return errors


def _cycle(by_id: dict) -> list[str]:
    colour: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> list[str]:
        if colour.get(node) == 1:
            return stack[stack.index(node):]
        if colour.get(node) == 2:
            return []
        colour[node] = 1
        for dep in by_id.get(node, {}).get("depends_on", []):
            found = visit(dep, stack + [dep])
            if found:
                return found
        colour[node] = 2
        return []

    for fid in by_id:
        found = visit(fid, [fid])
        if found:
            return found
    return []


# --------------------------------------------------------------------------- commands

def cmd_check(_args) -> int:
    data = load()
    errors = validate(data)
    lock = read_lock()
    current = lock_hash(data)

    if lock is None:
        errors.append("harness/features.lock missing -- run: harness.py relock")
    elif lock["sha256"] != current:
        errors.append(
            "FEATURE LOCK DRIFT: a locked field changed without a lock_version bump.\n"
            f"      expected {lock['sha256'][:16]}...  got {current[:16]}...\n"
            "      Locked fields are id, area, title, why, depends_on, acceptance, verify,\n"
            "      milestone. If the change is intentional: bump lock_version, add a\n"
            "      changelog entry saying what changed and why, then run relock.")
    elif lock["lock_version"] != data["lock_version"]:
        errors.append(f"lock file at v{lock['lock_version']}, ledger at "
                      f"v{data['lock_version']} -- run relock")

    if errors:
        print(f"{RED}FAIL{RESET} harness check")
        for e in errors:
            print(f"  - {e}")
        return 1

    counts = _counts(data)
    print(f"{GREEN}OK{RESET} harness check  "
          f"v{data['lock_version']}  {len(data['features'])} features  "
          f"{counts['done']} done / {counts['in_progress']} in progress / "
          f"{counts['locked']} locked")
    return 0


def _counts(data: dict) -> dict:
    out = {s: 0 for s in ("locked", "in_progress", "blocked", "done", "dropped")}
    for f in data["features"]:
        out[f["status"]] += 1
    return out


def _ready(data: dict) -> list[dict]:
    by_id = features_by_id(data)
    return [f for f in data["features"]
            if f["status"] == "locked"
            and all(by_id[d]["status"] in ("done", "dropped") for d in f["depends_on"])]


def cmd_status(_args) -> int:
    data = load()
    mark = {"done": f"{GREEN}[x]{RESET}", "in_progress": f"{YELLOW}[>]{RESET}",
            "blocked": f"{RED}[!]{RESET}", "locked": "[ ]", "dropped": f"{DIM}[-]{RESET}"}
    print(f"\n{data['project']} -- feature ledger v{data['lock_version']}\n")
    ready = {f["id"] for f in _ready(data)}
    area = None
    for f in data["features"]:
        if f["area"] != area:
            area = f["area"]
            print(f"  {DIM}{area}{RESET}")
        tag = " <- next" if f["id"] in ready and f["id"] == (
            _ready(data)[0]["id"] if _ready(data) else None) else ""
        blocked_on = [d for d in f["depends_on"]
                      if features_by_id(data)[d]["status"] not in ("done", "dropped")]
        wait = f"  {DIM}waits on {','.join(blocked_on)}{RESET}" if (
            blocked_on and f["status"] == "locked") else ""
        print(f"    {mark[f['status']]} {f['id']}  {f['title']}{tag}{wait}")
    c = _counts(data)
    print(f"\n  {c['done']} done, {c['in_progress']} in progress, {c['locked']} locked, "
          f"{c['blocked']} blocked\n")
    return 0


def cmd_next(_args) -> int:
    data = load()
    active = [f for f in data["features"] if f["status"] == "in_progress"]
    if active:
        print(f"{YELLOW}in progress:{RESET} {active[0]['id']}  {active[0]['title']}")
        print("finish or park it before starting another (policy: one_at_a_time)")
        return 0
    ready = _ready(data)
    if not ready:
        print("nothing actionable: every remaining feature is waiting on a dependency")
        return 1
    f = ready[0]
    _print_feature(f)
    print(f"\nstart with:  python scripts/harness.py start {f['id']}")
    return 0


def _print_feature(f: dict) -> None:
    print(f"\n{f['id']}  {f['title']}   [{f['status']}]  ({f['area']}, {f['milestone']})")
    print(f"\n  why: {f['why']}")
    if f["depends_on"]:
        print(f"\n  depends on: {', '.join(f['depends_on'])}")
    print("\n  acceptance:")
    for a in f["acceptance"]:
        print(f"    - {a}")
    print(f"\n  verify: {f['verify']}")
    if f.get("notes"):
        print(f"\n  notes: {f['notes']}")


def cmd_show(args) -> int:
    data = load()
    f = features_by_id(data).get(args.feature)
    if not f:
        print(f"no such feature: {args.feature}")
        return 1
    _print_feature(f)
    if f["sessions"]:
        print(f"\n  sessions: {', '.join(f['sessions'])}")
    return 0


def next_session_id() -> str:
    SESSIONS.mkdir(parents=True, exist_ok=True)
    existing = sorted(p.name[:4] for p in SESSIONS.glob("[0-9][0-9][0-9][0-9]-*.md"))
    return f"{int(existing[-1]) + 1:04d}" if existing else "0001"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "session"


SESSION_TEMPLATE = """# Session {sid} — {title}

*Date: {today}*
*Feature: {feature}*

## Goal

<!-- One sentence. What this session is trying to finish. -->

## Starting state

<!-- What was true at the start: test count, last result, open blockers. -->

## Log

### {today} — <entry title>

**What happened:**

**Decision:**

**Deviation from plan:**

**Next:**

## Verification run

```
$ {verify}
```

Result:

## Outcome

- [ ] Feature acceptance met
- [ ] Verify command exits 0
- [ ] Ledger updated
- [ ] research/discussion-record.md updated if a design decision was made

## Carried forward

<!-- What the next session needs to know. Assume no memory of this one. -->
"""


def cmd_session_new(args) -> int:
    data = load()
    feature = getattr(args, "feature", None)
    verify = "python scripts/harness.py check"
    if feature:
        f = features_by_id(data).get(feature)
        if not f:
            print(f"no such feature: {feature}")
            return 1
        verify = f["verify"]
    sid = next_session_id()
    title = args.title or (features_by_id(data)[feature]["title"] if feature else "session")
    path = SESSIONS / f"{sid}-{date.today()}-{_slug(title)}.md"
    path.write_text(SESSION_TEMPLATE.format(
        sid=sid, title=title, today=date.today(), feature=feature or "—", verify=verify))
    rebuild_progress()
    print(f"{GREEN}created{RESET} {path.relative_to(ROOT)}")
    return 0


def cmd_start(args) -> int:
    data = load()
    by_id = features_by_id(data)
    f = by_id.get(args.feature)
    if not f:
        print(f"no such feature: {args.feature}")
        return 1
    active = [x for x in data["features"] if x["status"] == "in_progress"]
    if active and active[0]["id"] != f["id"]:
        print(f"{RED}refused{RESET}: {active[0]['id']} is already in progress "
              f"(policy: one_at_a_time)")
        return 1
    waiting = [d for d in f["depends_on"] if by_id[d]["status"] not in ("done", "dropped")]
    if waiting:
        print(f"{RED}refused{RESET}: {f['id']} depends on unfinished {waiting}")
        return 1

    sid = next_session_id()
    f["status"] = "in_progress"
    f["started_at"] = str(date.today())
    f.setdefault("sessions", []).append(sid)
    save(data)

    path = SESSIONS / f"{sid}-{date.today()}-{_slug(f['title'])}.md"
    path.write_text(SESSION_TEMPLATE.format(
        sid=sid, title=f["title"], today=date.today(), feature=f["id"], verify=f["verify"]))
    rebuild_progress()
    _print_feature(f)
    print(f"\n{GREEN}started{RESET} -> {path.relative_to(ROOT)}")
    return 0


def run_verify(f: dict) -> int:
    print(f"{DIM}$ {f['verify']}{RESET}")
    return subprocess.run(f["verify"], shell=True, cwd=ROOT).returncode


def cmd_verify(args) -> int:
    data = load()
    f = features_by_id(data).get(args.feature)
    if not f:
        print(f"no such feature: {args.feature}")
        return 1
    code = run_verify(f)
    print(f"{GREEN}PASS{RESET}" if code == 0 else f"{RED}FAIL{RESET} (exit {code})")
    return code


def cmd_done(args) -> int:
    data = load()
    f = features_by_id(data).get(args.feature)
    if not f:
        print(f"no such feature: {args.feature}")
        return 1
    if not args.force:
        code = run_verify(f)
        if code != 0:
            print(f"{RED}refused{RESET}: verify exited {code}. Definition of done "
                  f"requires it to pass. Use --force only with a written justification "
                  f"in the session log.")
            return 1
    f["status"] = "done"
    f["completed_at"] = str(date.today())
    save(data)
    rebuild_progress()
    print(f"{GREEN}done{RESET} {f['id']}  {f['title']}")
    return cmd_next(args)


def cmd_relock(_args) -> int:
    data = load()
    errors = validate(data)
    if errors:
        print(f"{RED}refused{RESET}: ledger does not validate")
        for e in errors:
            print(f"  - {e}")
        return 1
    payload = write_lock(data)
    print(f"{GREEN}locked{RESET} v{payload['lock_version']}  "
          f"{payload['n_features']} features  sha256 {payload['sha256'][:16]}...")
    return 0


# --------------------------------------------------------------------------- progress

def rebuild_progress() -> None:
    """Regenerate the session index. The logs themselves are hand-written; this is a map."""
    data = load()
    SESSIONS.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(SESSIONS.glob("[0-9][0-9][0-9][0-9]-*.md")):
        sid, day = path.name[:4], path.name[5:15]
        first = ""
        for line in path.read_text().splitlines():
            if line.startswith("# Session"):
                first = line.split("—", 1)[-1].strip()
                break
        feats = [f["id"] for f in data["features"] if sid in f.get("sessions", [])]
        rows.append(f"| [{sid}]({path.name}) | {day} | {first} | {', '.join(feats) or '—'} |")

    c = _counts(data)
    body = f"""# Progress Log

Index of every working session. One file per session in `sessions/`. The files are the
durable memory of this project: each session starts with no recollection of the last one,
so anything not written here did not happen.

Generated by `python scripts/harness.py check`. Do not edit by hand — edit the session
files.

**Ledger v{data['lock_version']}** — {len(data['features'])} features:
{c['done']} done, {c['in_progress']} in progress, {c['locked']} locked, {c['blocked']} blocked.

| # | date | session | features |
|---|---|---|---|
""" + "\n".join(rows) + """

## How a session runs

1. `python scripts/harness.py next` — the single next actionable feature
2. `python scripts/harness.py start F-0NN` — marks it in progress, opens a session log
3. Work. Append to the session log as decisions happen, not at the end.
4. `python scripts/harness.py done F-0NN` — refuses unless the verify command passes
5. Design decisions also go to `research/discussion-record.md`, which is append-only

Exactly one feature is in progress at a time. That is enforced, not encouraged.
"""
    PROGRESS.write_text(body)


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check").set_defaults(fn=cmd_check)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("next").set_defaults(fn=cmd_next)
    sub.add_parser("relock").set_defaults(fn=cmd_relock)

    for name, fn in (("show", cmd_show), ("start", cmd_start), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("feature")
        p.set_defaults(fn=fn)

    p = sub.add_parser("done")
    p.add_argument("feature")
    p.add_argument("--force", action="store_true",
                   help="skip the verify gate; requires a written justification")
    p.set_defaults(fn=cmd_done)

    p = sub.add_parser("session-new")
    p.add_argument("title")
    p.add_argument("--feature", default=None)
    p.set_defaults(fn=cmd_session_new)

    args = ap.parse_args()
    code = args.fn(args)
    if args.cmd in ("check", "done", "start"):
        rebuild_progress()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
