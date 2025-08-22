SHELL   = /bin/bash
.ONESHELL:

.PHONY: clean
clean:
	$(RM) *~
	$(RM) -r jsutils/__pycache__ dist/

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
check: check.inline check.simpler check.src check.tests

.PHONY: check.src
check.src: check.ruff check.flake8 check.pyright

.PHONY: check.tests
check.tests: dev
	source venv/bin/activate
	$(MAKE) -C tests check

IGNORE  = E201,E202,E227,E302,E402,E731

.PHONY: check.ruff
check.ruff: venv
	source venv/bin/activate
	ruff check --ignore=$(IGNORE) jsutils

.PHONY: check.flake8
check.flake8: venv
	source venv/bin/activate
	flake8 --ignore=$(IGNORE),E128,E131,W504 --max-line-length=100 jsutils

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

.PHONY: check.stats
check.stats: venv
	source venv/bin/activate
	$(MAKE) -C tests stats

#
# publication on pypi
#
# pip install -e .[dist]
# make publish
# twine upload dist/*
#
.PHONY: publish
publish:
	source venv/bin/activate
	python -m build
	twine check dist/*
	echo "# twine upload dist/*"
