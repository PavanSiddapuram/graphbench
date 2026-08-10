.PHONY: dataset sample load bench validate sweep capped report lint typecheck test check

PYTHON ?= python3
PLATFORM ?=

dataset:
	$(PYTHON) cli.py dataset

sample: dataset
	$(PYTHON) cli.py sample

load:
	@test -n "$(PLATFORM)" || (echo "usage: make load PLATFORM=<name>  (see config/platforms.yaml)" && exit 1)
	$(PYTHON) cli.py load --platform $(PLATFORM)

bench:
	@test -n "$(PLATFORM)" || (echo "usage: make bench PLATFORM=<name>  (see config/platforms.yaml)" && exit 1)
	$(PYTHON) cli.py bench --platform $(PLATFORM)

validate:
	$(PYTHON) cli.py validate

sweep:
	@test -n "$(PLATFORM)" || (echo "usage: make sweep PLATFORM=<name>  (see config/platforms.yaml)" && exit 1)
	$(PYTHON) cli.py sweep --platform $(PLATFORM)

# Stage F (Track B: capped self-hosted memory sweep) was not executed in
# the environment this repo was built in - see results/failures.md. The
# compose file exists (docker/compose.capped.yml) but the sweep loop that
# would drive it and record OOM boundaries has not been written or run.
capped:
	@echo "make capped is not implemented - see results/failures.md (Track B was not run)" && exit 1

report:
	$(PYTHON) cli.py report

lint:
	ruff check .

typecheck:
	mypy --strict graphbench/ cli.py analysis/

test:
	pytest -q

check: lint typecheck test
