target:
	@fgrep -h "##" $(MAKEFILE_LIST) | fgrep -v fgrep | sed -e 's/\\$$//' | sed -e 's/##//'

install: ## Install the dependencies
	pip install .

uninstall: ## Uninstall the dependencies
	pip uninstall discord_slash_webhook -y

reinstall: uninstall install ## Reinstall the dependencies
