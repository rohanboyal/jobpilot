.PHONY: install dev serve build crawl score cycle test lint doctor launchd-install launchd-remove

install:        ## install python + node deps and the browser
	uv sync
	uv run playwright install chromium
	cd web && npm install

dev:            ## run API (8000) + Vite dev server (5173) with hot reload
	./scripts/dev.sh

build:          ## build the UI into web/dist (served by the API)
	cd web && npm run build

serve: build    ## production-style: API + built UI on http://127.0.0.1:8000
	uv run jobagent serve

crawl:
	uv run jobagent crawl

score:
	uv run jobagent score

cycle:
	uv run jobagent cycle

test:
	uv run pytest -q

lint:
	uv run ruff check backend
	cd web && npm run typecheck

doctor:
	uv run jobagent doctor

launchd-install: ## keep the server (and its scheduler) running in the background on login
	./scripts/launchd.sh install

launchd-remove:
	./scripts/launchd.sh remove
