.PHONY: check bundle image preflight
check:
	.venv/bin/python -m pytest -q
	npm run check
bundle:
	npm run build
image:
	docker build -t offence:lab .
preflight:
	.venv/bin/python scripts/preflight.py
