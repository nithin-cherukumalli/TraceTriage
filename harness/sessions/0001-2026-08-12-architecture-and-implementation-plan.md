# Session 0001 — Repository architecture and implementation plan

*Date: 2026-08-12*
*Feature: F-001*

> Retro-logged during session 0005, when the harness was installed. Reconstructed from the
> artefacts produced, not from a contemporaneous record. Sessions 0005 onward are written
> as they happen.

## Goal

Turn a research question into a repository architecture and an implementation plan, and
challenge the assumptions in the brief before any code exists.

## Starting state

Empty folder. A research brief: adaptive diagnostic agent, five-mechanism taxonomy, six
probes, three policies, six metrics.

## Log

### 2026-08-12 — Three decisions taken before writing code

**What happened:** Asked three questions that changed the architecture rather than
proceeding on assumptions — trace source, probe semantics, and policy implementation.
Answers: synthetic generator first with real-dataset adapters stubbed; probes as read-only
unredaction of a stored trace; scripted policies first with the LLM behind an interface.

Searched for prior art. Found TRAIL (Patronus, arXiv:2505.08638), Who&When (ag2ai), and
AgenTracer. All perform one-shot attribution over a fully visible trace. None treats
evidence gathering as a decision — that gap is the contribution.

**Decision:** Four assumptions in the brief were challenged in writing.

1. "Adaptive beats fixed" is near-tautological against a weak fixed baseline. Introduced
   **B2-strong**, the optimal fixed probe order searched on dev, and required it to be
   built *before* the adaptive policy so its number is never seen first.
2. Designing the fault injector and the probes together makes the result circular.
   Mitigated by freezing the probe contract before the generator exists, deriving labels
   from construction rather than annotation, and narrowing the claim in writing.
3. Localization is trivial unless the corpus separates `root_cause_step` from `crash_step`.
   Became corpus requirement G1 (≥ 40%).
4. H5 cannot be a predicted class. Realised as held-out families present only in test.

**Deviation from plan:** None — this session produced the plan.

**Next:** Freeze the specs, then build the model and probe layer.

## Verification run

```
$ pytest -q
```

Result: 17 passed (initial `adiag` scaffold, later superseded).

## Outcome

- [x] Architecture and plan delivered
- [x] Specs frozen before implementation
- [x] Scaffold green

## Carried forward

The four challenges above are the spine of the project. B2-strong before the adaptive
policy is a sequencing constraint, not a preference.
