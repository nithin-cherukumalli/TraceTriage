# AGENTS.md

> Project-level instructions for AI agents working in this repository.
> Read this before starting any task. Structure follows
> [awesome-harness-engineering](https://github.com/ai-boost/awesome-harness-engineering).

## Project overview

`agent-diagnosis` is a research repository testing one question: when an AI agent fails and
several failure mechanisms are possible, can an adaptive diagnostic agent choose better
evidence-gathering actions than fixed debugging procedures? A diagnostic agent receives a
**redacted** failed execution trace, pays from a bounded probe budget to reveal specific
evidence, and must then name the failure mechanism or escalate.

Python 3.11+, standard library only for the core (pytest for tests). No network at test
time. This is an experiment, not a product: **the deliverable is a defensible result, and a
result that fails its hypothesis is still a deliverable.**

## Repository structure

```
research/       scientific record — written BEFORE the code it governs
harness/        feature ledger, session logs, plan, implementation log
schemas/        trace_schema.json — the visibility boundary, machine-readable
src/trace/      data model, parser, case generator, corpus verifier
src/probes/     the six contract probes, one file each
src/diagnosis/  taxonomy, belief, policies, episode loop
src/baselines/  comparison baselines (B1 whole-trace LLM) — imports nothing from probes
src/llm/        provider-agnostic client; MockClient is the offline default
src/evaluation/ metrics, experiment runner
experiments/    corpus builders and experiment drivers
tests/          contract tests + harness tests
data/           generated corpora
results/        run outputs
paper/          write-up
scripts/        harness.py CLI
```

## The four things that make this repository unusual

Read these before changing anything, because they are load-bearing and easy to break by
accident.

1. **`research/probe-contract.md` is FROZEN.** It was dated before the case generator
   existed. That ordering is the defence against the charge that probes were tuned to the
   corpus. Never edit it in place — append a dated amendment stating the change, the
   rationale, and its consequence.

2. **Ground truth must be unreachable, not merely unread.** The environment owns `Trace`
   (and therefore `GroundTruth`); a policy receives only an `Observation`, built solely by
   `make_observation()`. `tests/test_contract.py` walks the object graph and asserts this.
   Do not add a back-pointer, a corpus handle, or a trace-id lookup to any policy.

3. **Never let the artefact under test judge the data it is tested on.** The corpus
   verifier once used the policy's belief model to decide whether cases were solvable and
   condemned eight sound cases because the belief model has a known defect. Corpus
   sufficiency is checked by subset existence over the evidence, independent of any
   reasoner.

4. **Do not tune a policy to pass a kill criterion.** `research/preregistration.md` states
   what happens when each criterion fires. If the adaptive policy loses, that is the
   finding. Write it down, diagnose the cause, fix the cause — do not adjust thresholds
   until the number moves.

## Conventions

### Code style

PEP 8, 4-space indent, ~90 column soft limit. Type hints on public functions.
`from __future__ import annotations` at the top of every module.

Docstrings carry the *why*, not the *what*. A module docstring that restates the module
name is noise; one that records why a design was chosen over the obvious alternative is the
most valuable thing in the file. Several modules here document a mistake that was made and
reverted — keep those.

### Naming

Files snake_case, classes CapWords, constants UPPER_SNAKE. Probe modules are named after
the probe (`schema_probe.py`), and the probe's `spec.id` is the canonical identifier used
in configs, results and the contract.

### Testing

```bash
pytest -q                                  # full suite, offline, < 1s
pytest tests/test_contract.py -q           # contract + leakage + corpus invariants
pytest tests/test_harness.py -q            # feature lock + session log integrity
pytest tests/test_baselines.py -q          # B1 formatting, parsing, grounding, leakage
```

A passing suite means every contract invariant holds. It does **not** mean a result is
valid — that is what `research/preregistration.md` is for.

### Commits

Present tense, one logical change. Reference the feature id when one applies:
`F-011: rebuild belief from evidence list to remove order dependence`.
Branch off `main`; do not push to `main` directly.

## Working method: one feature at a time

Work is tracked in `harness/features.json`, a **locked ledger**. Locked fields (`id`,
`area`, `title`, `why`, `depends_on`, `acceptance`, `verify`, `milestone`) are covered by a
SHA-256 in `harness/features.lock`. Changing one without bumping `lock_version` and adding
a changelog entry fails `harness.py check`, and therefore CI.

```bash
python scripts/harness.py next            # the single next actionable feature
python scripts/harness.py start F-0NN     # marks in progress, opens a session log
python scripts/harness.py verify F-0NN    # runs that feature's verify command
python scripts/harness.py done F-0NN      # refuses unless verify exits 0
python scripts/harness.py status          # whole ledger
```

Exactly one feature may be `in_progress`; the CLI refuses a second. **Every session writes
a log** in `harness/sessions/`, appended as work happens rather than reconstructed at the
end. Assume the next session remembers nothing: anything not written down did not happen.

Design decisions also go to `research/discussion-record.md`, which is append-only.

## Tool permissions

**Allowed**

- Read and edit anything under `src/`, `tests/`, `experiments/`, `harness/sessions/`
- Append to `research/discussion-record.md`
- Run `pytest`, `python scripts/harness.py *`, `python experiments/*.py`
- Regenerate `data/synthetic_cases/` and `results/`

**Restricted — state the reason in the session log before proceeding**

- `harness/features.json` locked fields (requires `lock_version` bump + changelog)
- `research/probe-contract.md` (append-only amendment; never edit in place)
- `research/preregistration.md` after the test split has been scored
- `schemas/trace_schema.json` visibility tiers
- Probe prices in `src/probes/base.py`

**Not allowed**

- Weakening or deleting a test in `tests/test_contract.py` to make a change pass
- Importing anything from `src/probes/` into `src/baselines/` — B1 is defined by what it
  cannot do, and a test scans for it
- Optimising a baseline: no prompt iteration on dev, no retry-until-parse, no tuning B1 to
  look better or worse than it is
- Giving any policy access to `Trace` or `GroundTruth`
- Running the pre-registered experiment (F-022) on a seed that has been scored before
- Adding dependencies without explicit instruction; the core stays standard-library
- Network access in tests — `MockClient` keeps the suite offline

## Known constraints

- `src/` is on the path via `pyproject.toml`'s `pythonpath`, and the package is named
  `trace`, which **shadows the stdlib `trace` module**. Nothing here imports stdlib
  `trace`; if you ever need it, import it before `sys.path` is modified.
- `Belief` is rebuilt from the full evidence list every turn, not updated incrementally.
  Cross-evidence signatures make incremental updates order-dependent. Do not "optimise"
  this back into an incremental update.
- The likelihood table in `src/diagnosis/belief.py` assumes independence between
  observations and is **known to be wrong**. It is the subject of F-011. Do not patch
  around it elsewhere.
- Seeds 0 and 1000 are burned for diagnostics and must not be used for E1.

## Verification gates

Before marking any task complete:

- [ ] `pytest -q` passes
- [ ] `python scripts/harness.py check` passes (schema, lock, dependency order, one-at-a-time)
- [ ] `python experiments/build_cases.py` passes G1–G7 if anything touched the generator,
      probes, or the belief layer
- [ ] the feature's own `verify` command exits 0
- [ ] the session log records what happened, including anything that did not work
- [ ] changed files are within the permitted scope above

## Escalation

If a decision is needed that falls outside the permitted scope — a taxonomy change, a
contract amendment, touching the test split, or anything that would require tuning a policy
to satisfy a kill criterion — **stop and describe the blocker.** Do the preparatory work
that is safe, write the options and their consequences into the session log, and leave the
decision. Guessing here does not cost a bug; it costs the result.
