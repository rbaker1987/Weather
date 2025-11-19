.PHONY: help lint lint-fix format test clean install

help:
	@echo "Available commands:"
	@echo "  make install     - Install all dependencies"
	@echo "  make lint        - Run all linters"
	@echo "  make lint-fix    - Run linters and auto-fix issues"
	@echo "  make format      - Format all code"
	@echo "  make test        - Run tests"
	@echo "  make clean       - Clean cache files"
	@echo "  make pre-commit  - Install pre-commit hooks"

install:
	pip install -e ".[dev,django]"
	npm install

lint:
	@echo "Running Python linter..."
	ruff check .
	@echo "Running JavaScript linter..."
	npm run lint:js

lint-fix:
	@echo "Fixing Python issues..."
	ruff check --fix .
	@echo "Fixing JavaScript issues..."
	npm run lint:js:fix

format:
	@echo "Formatting Python..."
	ruff format .
	@echo "Formatting JavaScript/CSS..."
	npm run format

test:
	cd weather_app && python manage.py test

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	rm -rf node_modules

pre-commit:
	pre-commit install
	@echo "Pre-commit hooks installed!"
