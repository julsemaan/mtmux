PYTHON ?= python3

.PHONY: test dev-install

test:
	$(PYTHON) -m unittest discover -s tests

dev-install:
	$(PYTHON) -m pip install -e . --break-system-packages
