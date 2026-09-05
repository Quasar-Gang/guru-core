.PHONY: check test lint type imports fmt integration
check: lint type imports test
# --no-cache because a stale ruff cache has silently passed a file that CI then
# rejected. At this size the cache saves ~10ms and costs a red build.
lint:
	uv run ruff check --no-cache .
	uv run ruff format --check .
fmt:
	uv run ruff format .
	uv run ruff check --no-cache --fix .
type:
	uv run mypy .
imports:
	uv run lint-imports
test:
	uv run pytest
integration:
	uv run pytest -m integration

# --- Deployment -------------------------------------------------------------
# Two configurations, same targets:
#   make deploy env=local        # build, start, migrate, seed
#   make deploy env=production   # same, on the Droplet, reading .env.production
# Not wired into CI; run these by hand from a checkout.

env ?= local
deploy_dir := deployment/$(env)
compose_file := $(deploy_dir)/docker-compose.yml
env_file := $(deploy_dir)/.env.$(env)
# local carries its throwaway values inline and has no env file.
COMPOSE = docker compose $(if $(wildcard $(env_file)),--env-file $(env_file),) -f $(compose_file)

.PHONY: deploy-validate
deploy-validate:
	@test -f $(compose_file) || { echo "unknown env '$(env)': expected local or production"; exit 1; }
	@if [ "$(env)" = "production" ] && [ ! -f $(env_file) ]; then \
		echo "missing $(env_file) — copy $(env_file).example and fill it in"; exit 1; \
	fi

.PHONY: deploy-help
deploy-help:
	@echo "guru-core deployment (env=local | production, default local)"
	@echo ""
	@echo "  make deploy env=<env>          build + up + migrate + seed"
	@echo "  make deploy-build env=<env>    build the image"
	@echo "  make deploy-up env=<env>       start the stack"
	@echo "  make deploy-down env=<env>     stop the stack (data survives)"
	@echo "  make deploy-migrate env=<env>  alembic upgrade head"
	@echo "  make deploy-seed env=<env>     seed role models"
	@echo "  make deploy-ps env=<env>       container status"
	@echo "  make deploy-logs env=<env>     follow logs"
	@echo "  make deploy-config env=<env>   render the resolved compose file"
	@echo "  make deploy-smoke env=<env>    end-to-end smoke against the running API"
	@echo ""
	@echo "  current: env=$(env)  file=$(compose_file)"

.PHONY: deploy
deploy: deploy-build deploy-up deploy-migrate deploy-seed
	@echo "deployed ($(env)). check: make deploy-ps env=$(env)"

.PHONY: deploy-build
deploy-build: deploy-validate
	$(COMPOSE) build

.PHONY: deploy-up
deploy-up: deploy-validate
	$(COMPOSE) up -d

.PHONY: deploy-down
deploy-down: deploy-validate
	$(COMPOSE) down

.PHONY: deploy-restart
deploy-restart: deploy-validate
	$(COMPOSE) restart

.PHONY: deploy-ps
deploy-ps: deploy-validate
	$(COMPOSE) ps

.PHONY: deploy-logs
deploy-logs: deploy-validate
	$(COMPOSE) logs -f --tail=200

.PHONY: deploy-config
deploy-config: deploy-validate
	$(COMPOSE) config

# The image entrypoint is `python -m`, so the command is the module and its args.
.PHONY: deploy-migrate
deploy-migrate: deploy-validate
	$(COMPOSE) run --rm api alembic upgrade head

.PHONY: deploy-seed
deploy-seed: deploy-validate
	$(COMPOSE) run --rm api cmd.seed_role_models

.PHONY: deploy-smoke
deploy-smoke: deploy-validate
	API_BASE=$(if $(filter production,$(env)),$(shell sed -n 's/^PUBLIC_BASE_URL=//p' $(env_file)),http://127.0.0.1:8000) \
		bash scripts/smoke.sh
