"""Taxonomy: mechanisms, the eleven failure families, and the held-out family.

Single source of truth for what the generator may produce and what a policy may predict.
The two sets differ on purpose: held-out families are generatable but not predictable,
which is what makes H5 an escalation problem rather than a fifth classification label.

TAXONOMY REVISION 2026-08-12
---------------------------
`wrong_tool_selected` moved H2 -> H1 at the researcher's direction. Selecting the wrong
tool is a decision error, not an interaction error; the tool was invoked correctly and
behaved correctly. Consequence accepted deliberately: H1 and H2 now both surface at
`tool_call` steps and are genuinely confusable, so no single probe separates them. Harder,
and closer to real debugging.

Family count went 6 -> 11, which supersedes the earlier "six initial families" scope
decision. At n=400 that is ~36 cases per family, thin but workable for stratified error
analysis; at n=40 it is ~3.6, which is an inspection corpus and nothing more.
"""
from __future__ import annotations

from dataclasses import dataclass

from trace.models import Mechanism


@dataclass(frozen=True)
class Family:
    id: str
    mechanism: Mechanism
    description: str
    in_taxonomy: bool = True
    #: True when the root cause is separated from the crash by at least one step.
    displaces_root_cause: bool = False
    #: True when no single probe reveals the fault -- it only appears when two pieces of
    #: evidence are held against each other. These are the cases that justify the project.
    needs_cross_evidence: bool = False


FAMILIES: dict[str, Family] = {
    f.id: f for f in (
        # ---------------------------------------------------------------- H1 planning
        Family("wrong_tool_selected", Mechanism.H1_PLANNING,
               "Schema-valid call to a tool that cannot serve the subgoal. The tool "
               "behaves perfectly; the decision to call it was wrong.",
               displaces_root_cause=True),
        Family("wrong_reasoning_decision", Mechanism.H1_PLANNING,
               "Correct evidence is retrieved and read, and the wrong conclusion is "
               "drawn from it.",
               displaces_root_cause=True, needs_cross_evidence=True),
        Family("incorrect_routing", Mechanism.H1_PLANNING,
               "The request is routed into a workflow that does not match the task.",
               displaces_root_cause=True),

        # ---------------------------------------------------------------- H2 tool
        Family("malformed_arguments", Mechanism.H2_TOOL,
               "Argument value violates the declared type."),
        Family("schema_mismatch", Mechanism.H2_TOOL,
               "Argument names do not match the tool contract: a required field is "
               "absent and an unrecognised one is supplied."),
        Family("misunderstood_output", Mechanism.H2_TOOL,
               "The tool returns a correct, healthy response and the agent misreads it.",
               displaces_root_cause=True, needs_cross_evidence=True),

        # ---------------------------------------------------------------- H3 context
        Family("missing_context", Mechanism.H3_CONTEXT,
               "Retrieval returns nothing usable; the agent proceeds anyway."),
        Family("wrong_retrieved_information", Mechanism.H3_CONTEXT,
               "Retrieval returns a superseded document; the agent then reasons "
               "correctly over wrong evidence.",
               displaces_root_cause=True),

        # ---------------------------------------------------------------- H4 external
        Family("api_failure", Mechanism.H4_EXTERNAL,
               "The tool's backing service returns a server error on valid input."),
        Family("service_unavailable", Mechanism.H4_EXTERNAL,
               "The service does not respond: timeout after elevated latency."),

        # ---------------------------------------------------------------- H5 held out
        Family("silent_state_corruption", Mechanism.H5_UNKNOWN,
               "The failure lives in unlogged agent state. Every step is individually "
               "clean and no probe in the contract can localize it.",
               in_taxonomy=False),
    )
}

IN_TAXONOMY_FAMILIES = tuple(f.id for f in FAMILIES.values() if f.in_taxonomy)
HELD_OUT_FAMILIES = tuple(f.id for f in FAMILIES.values() if not f.in_taxonomy)
CROSS_EVIDENCE_FAMILIES = tuple(f.id for f in FAMILIES.values() if f.needs_cross_evidence)
PREDICTABLE = Mechanism.predictable()


def families_for(mechanism: Mechanism) -> tuple[str, ...]:
    return tuple(f.id for f in FAMILIES.values()
                 if f.mechanism is mechanism and f.in_taxonomy)


def mechanism_of(family_id: str) -> Mechanism:
    return FAMILIES[family_id].mechanism
