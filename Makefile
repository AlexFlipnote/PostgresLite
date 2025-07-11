target:
	@echo -e "\033[1mPostgresLite v$(shell grep -oP '(?<=__version__ = ")[^"]*' postgreslite/__init__.py)\033[0m" \
	"\nUse 'make \033[0;36mtarget\033[0m' where \033[0;36mtarget\033[0m is one of the following:"
	@awk -F ':|##' '/^[^\t].+?:.*?##/ { printf " \033[0;36m%-15s\033[0m %s\n", $$1, $$NF }' $(MAKEFILE_LIST)

# Production tools
install:  ## Install the package
	pip install .

uninstall:  ## Uninstall the package
	pip uninstall -y discord.http

reinstall: uninstall install  ## Reinstall the package

# Development tools
install_dev:	 ## Install the package in development mode
	uv sync --all-extras || pip install .[dev]

venv:  ## Create a virtual environment
	uv venv || python -m venv .venv

type:  ## Run pyright on the package
	@uv run pyright postgreslite --pythonversion 3.11 || pyright postgreslite --pythonversion 3.11

lint:  ## Run ruff linter
	@uv run ruff check --config pyproject.toml || ruff check --config pyproject.toml

clean:  ## Clean the project
	@rm -rf build dist *.egg-info .venv docs/_build
	@rm uv.lock

# Maintainer-only commands
upload_pypi:  ## Maintainer only - Upload latest version to PyPi
	@echo Uploading to PyPi...
	uv build
	uvx uv-publish
	@echo Done!
