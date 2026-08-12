import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evaluation.experiment_runner import build_corpus   # noqa: E402
from trace.synthesize import GeneratorConfig, generate_case  # noqa: E402
import random  # noqa: E402


@pytest.fixture(scope="session")
def dev_corpus():
    return build_corpus(seed=0, n_cases=60, include_held_out=False)


@pytest.fixture(scope="session")
def test_corpus():
    return build_corpus(seed=99, n_cases=60, include_held_out=True)


@pytest.fixture
def stale_case():
    """Displaced root cause: stale retrieval early, refund rejection several steps later."""
    case, _ = generate_case("wrong_retrieved_information", 1, GeneratorConfig(),
                            random.Random(7))
    return case


@pytest.fixture(scope="session")
def inspection_corpus():
    """Stratified: every family guaranteed to appear."""
    from evaluation.experiment_runner import Corpus
    from trace.synthesize import generate
    cases, refs = generate(GeneratorConfig(seed=7, n_cases=44, include_held_out=True,
                                           allocation="by_family"))
    return Corpus(cases, refs)
