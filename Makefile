SHELL   = /bin/bash
.ONESHELL:

.PHONY: clean
clean:
	$(RM) *~
	$(RM) -r jsutils/__pycache__

.PHONY: clean.dev
clean.dev: clean
	$(RM) -rf venv *.egg-info

.PHONY: dev
dev: venv

venv:
	python -m venv venv
	source venv/bin/activate
	pip install -e .[dev]

.PHONY: check
check: check.inline check.simpler check.ruff check.flake8 check.pyright

IGNORE  = E201,E202,E227,E402

.PHONY: check.ruff
check.ruff: venv
	source venv/bin/activate
	ruff check --ignore=$(IGNORE) jsutils

.PHONY: check.flake8
check.flake8: venv
	source venv/bin/activate
	flake8 --ignore=$(IGNORE) --max-line-length=100 jsutils

.PHONY: check.pyright
check.pyright: venv
	source venv/bin/activate
	pyright jsutils

.PHONY: check.inline
check.inline: venv
	source venv/bin/activate
	$(MAKE) -C tests inline

.PHONY: check.simpler
check.simpler: venv
	source venv/bin/activate
	$(MAKE) -C tests simpler
