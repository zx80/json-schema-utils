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
