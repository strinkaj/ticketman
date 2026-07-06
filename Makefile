.PHONY: help setup install dev lint test sensors find plan watch status

.DEFAULT_GOAL := help

help:
	@echo "ticketman - available targets:"
	@echo "  make setup     create venv and install with dev deps"
	@echo "  make install   install package in editable mode"
	@echo "  make dev       install with dev dependencies"
	@echo "  make lint      run ruff linter"
	@echo "  make test      run pytest with coverage"
	@echo "  make sensors   run the full quality gate (lint, tests+coverage, security)"
	@echo "  make status    show config and roster summary"
	@echo ""
	@echo "usage examples:"
	@echo "  ticketman find \"artist name\" --city Boston"
	@echo "  ticketman info <event-id>"
	@echo "  ticketman plan <event-id> --quantity 4"
	@echo "  ticketman watch <event-id> --interval 60"
	@echo "  ticketman roster add \"Joe\" --email joe@example.com --access amex,verified-fan"

setup:
	python -m venv .venv
	.venv/Scripts/pip install -e ".[dev]"

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

lint:
	ruff check src/ tests/

test:
	pytest --cov=ticketman --cov-report=term-missing

# Deterministic quality gate. Fix the underlying issue, never the message.
sensors:
	ruff check src/ tests/
	pytest --cov=ticketman --cov-report=term-missing --cov-fail-under=75
	bandit -q -r src/
	pip-audit

status:
	ticketman status
