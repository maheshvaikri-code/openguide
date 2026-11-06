# OpenGuide developer targets.
.PHONY: test lint demo corporate-demo cyber-demo bench fleet conformance quickstart all \
	console-install console-build console-test console-demo

test:
	python -m pytest

lint:
	python -m ruff check .

conformance:
	python spec/conformance/run_conformance.py

# The killer demo: baseline drifts vs governed holds (simulated, no network/GPU).
demo:
	python examples/demo/run.py

# Corporate reference demo: live SEC EDGAR data + proxy tool-action governance.
corporate-demo:
	python examples/corporate-edgar/run.py --refresh --tickers AAPL MSFT

# Cyber risk reference demo: live CISA KEV data + proxy tool-action governance.
cyber-demo:
	python examples/cyber-kev/run.py --refresh --vendors Microsoft Apple

quickstart:
	python examples/quickstart-proxy/run.py

# Simulated benchmarks (real-model numbers require API keys/weights).
bench:
	python benchmarks/t1_bench.py
	python benchmarks/drift_bench.py

# Generate a synthetic fleet into a sqlite db for the Console's Fleet view.
fleet:
	python benchmarks/fleet_gen.py --n 10000 --db fleet.db

# Console (Vite + React + TypeScript). Needs Node 20+.
console-install: console/node_modules

# Installs only when needed (first run, or the lockfile changed).
console/node_modules: console/package-lock.json
	cd console && npm ci
	touch console/node_modules

console-build: console/node_modules
	cd console && npm run build

console-test: console/node_modules
	cd console && npm run typecheck && npm test

# Seed simulated data and serve proxy + Console at http://127.0.0.1:8088/console/
console-demo: console-build
	python scripts/console_demo.py

all: lint test conformance
