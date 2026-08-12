.PHONY: help install test check status next verify cases corpus experiment all

help:
	@echo "make install    editable install with dev extras"
	@echo "make check      harness gate: schema, feature lock, dependency order"
	@echo "make test       full test suite (offline)"
	@echo "make cases      build + verify the 40-case inspection corpus (G1-G7)"
	@echo "make corpus     build + verify the dev/test experimental corpora"
	@echo "make status     the feature ledger"
	@echo "make next       the single next actionable feature"
	@echo "make all        everything CI runs"

install:
	pip install -e ".[dev]"

check:
	python scripts/harness.py check

status:
	python scripts/harness.py status

next:
	python scripts/harness.py next

test:
	pytest -q

cases:
	python experiments/build_cases.py

corpus:
	python experiments/validate_corpus.py

experiment:
	python experiments/run_experiment.py

all: check test cases
	@echo "all gates green"
