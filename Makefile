.PHONY: help setup install dev lint test run login

help:
	@echo "ticketman — available targets:"
	@echo "  make setup     create venv, install deps, install playwright browsers"
	@echo "  make install   install package in editable mode"
	@echo "  make dev       install with dev dependencies"
	@echo "  make lint      run ruff linter"
	@echo "  make test      run pytest"
	@echo "  make login     launch browser for Ticketmaster login"
	@echo "  make run       start the bot (uses config/config.yaml)"

setup:
	python -m venv .venv
	.venv/Scripts/pip install -e ".[dev,sms]"
	.venv/Scripts/playwright install chromium

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

lint:
	ruff check src/ tests/

test:
	pytest

login:
	ticketman login

run:
	ticketman run
