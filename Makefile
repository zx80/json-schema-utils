SHELL   = /bin/bash
.ONESHELL:

.PHONY: clean
clean:
	$(RM) *~
	$(RM) -r jsutils/__pycache__

.PHONY: clean.dev
clean.dev:
	$(RM) -rf venv *.egg-info

.PHONY: dev
dev: venv

venv:
	python -m venv venv
	source venv/bin/activate
	pip install -e .

.PHONY: check
check: check.inline check.ruff check.flake8

IGNORE  = E201,E202,E227,E402

.PHONY: check.ruff
check.ruff: venv
	ruff check --ignore=$(IGNORE) jsutils

.PHONY: check.flake8
check.flake8:
	flake8 --ignore=$(IGNORE) --max-line-length=100 jsutils

.PHONY: check.inline
check.inline: venv
	$(MAKE) -C tests inline
