# Sworn — phase-gated build. `make phase-N` runs that phase's checks and records the
# result in PHASES.md, and only records DONE when every check passed.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PY := .venv/bin/python
PHASES := 0 1 2 3 4 5 6 7 8 9 10 11

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_%-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@printf '  \033[36m%-18s\033[0m %s\n' 'phase-N' 'Run the gate for phase N (0..11) and record it'

.PHONY: install
install: ## Install every toolchain dependency (node, python, foundry submodules)
	pnpm install --frozen-lockfile || pnpm install
	git submodule update --init --recursive
	python3 -m venv .venv
	$(PY) -m pip install --quiet --upgrade pip setuptools wheel
	$(PY) -m pip install --quiet -e "analysis[dev]"

.PHONY: build
build: ## Build contracts and TS packages
	cd contracts && forge build
	pnpm -r --if-present build

.PHONY: test
test: test-contracts test-ts test-py ## Run every test suite

.PHONY: test-contracts
test-contracts: ## Foundry unit + fuzz tests
	cd contracts && forge test

.PHONY: test-fork
test-fork: ## Foundry fork tests (needs archive RPCs in .env)
	cd contracts && forge test --match-path 'test/fork/*' -vv

.PHONY: test-ts
test-ts: ## Workspace TS tests
	pnpm -r --if-present test

.PHONY: test-py
test-py: ## Python pipeline tests
	cd analysis && ../$(PY) -m pytest

.PHONY: lint
lint: ## Lint everything
	cd contracts && forge fmt --check
	pnpm format:check
	$(PY) -m ruff check analysis
	$(PY) -m ruff format --check analysis

.PHONY: fmt
fmt: ## Autoformat everything
	cd contracts && forge fmt
	pnpm format
	$(PY) -m ruff check --fix analysis
	$(PY) -m ruff format analysis

.PHONY: typecheck
typecheck: ## TS strict typecheck
	pnpm -r --if-present typecheck

.PHONY: gate-selftest
gate-selftest: ## Prove the runner refuses to mark a failing phase
	./scripts/mark-phase.sh --selftest

$(addprefix phase-,$(PHASES)): phase-%:
	@./scripts/mark-phase.sh $*

.PHONY: clean
clean: ## Remove build output (keeps .venv and node_modules)
	cd contracts && forge clean
	rm -rf $(addsuffix /dist,index probe attestor sdk app) app/.next
