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
# Two configurations, one set of targets. The env decides *where* the work runs:
#
#   make deploy env=local        containers on this machine
#   make deploy env=production   rsync to the Droplet, then run it there over SSH
#
# Not wired into CI; run these by hand.

env ?= local
deploy_dir := deployment/$(env)
compose_file := $(deploy_dir)/docker-compose.yml
env_file := $(deploy_dir)/.env.$(env)
# local carries its throwaway values inline and has no env file.
compose_cmd = docker compose $(if $(wildcard $(env_file)),--env-file $(env_file),) -f $(compose_file)

# Where production lives. Override on the command line if the host ever moves.
ssh_host ?= guru-backend
remote_dir ?= /opt/guru-core

# For production every docker command runs on the Droplet; for local, right here.
ifeq ($(env),production)
RUN = ssh $(ssh_host) 'cd $(remote_dir) && $(1)'
else
RUN = $(1)
endif

# Caches and virtualenvs are big and useless there. deployment/*/data is the
# Droplet's own database — never let --delete near it.
rsync_excludes := --exclude .venv --exclude .git --exclude .data --exclude .env \
	--exclude .mypy_cache --exclude .pytest_cache --exclude .ruff_cache \
	--exclude .import_linter_cache --exclude __pycache__ --exclude dist \
	--exclude 'deployment/*/data'

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
	@echo "  local runs containers here; production rsyncs to $(ssh_host):$(remote_dir)"
	@echo "  and runs every docker command there over SSH."
	@echo ""
	@echo "  make deploy env=<env>            sync + build + up + migrate + seed"
	@echo "  make deploy-bootstrap            install docker and open the firewall (production only)"
	@echo "  make deploy-sync                 rsync the working tree to the Droplet"
	@echo "  make deploy-build env=<env>      build the image"
	@echo "  make deploy-up env=<env>         start the stack"
	@echo "  make deploy-down env=<env>       stop the stack (data survives)"
	@echo "  make deploy-migrate env=<env>    alembic upgrade head"
	@echo "  make deploy-seed env=<env>       seed role models"
	@echo "  make deploy-ps env=<env>         container status"
	@echo "  make deploy-logs env=<env>       follow logs"
	@echo "  make deploy-config env=<env>     render the resolved compose file"
	@echo "  make deploy-smoke env=<env>      end-to-end smoke against the running API"
	@echo ""
	@echo "  current: env=$(env)  file=$(compose_file)"

.PHONY: deploy
deploy: deploy-sync deploy-build deploy-up deploy-migrate deploy-seed
	@echo "deployed ($(env)). check: make deploy-ps env=$(env)"

# One-time Droplet preparation. Idempotent — safe to re-run.
.PHONY: deploy-bootstrap
deploy-bootstrap:
	@test "$(env)" = "production" || { echo "deploy-bootstrap is production-only"; exit 1; }
	ssh $(ssh_host) 'command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh'
	# 80 is needed for the Let's Encrypt HTTP-01 challenge, not just redirects.
	ssh $(ssh_host) 'ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw --force enable'
	# The API used to be published here; Caddy fronts it now.
	ssh $(ssh_host) 'ufw delete allow 8000 || true'
	ssh $(ssh_host) 'mkdir -p $(remote_dir)'

# No-op for local: there is nothing to send anywhere.
.PHONY: deploy-sync
deploy-sync: deploy-validate
ifeq ($(env),production)
	rsync -a --delete $(rsync_excludes) ./ $(ssh_host):$(remote_dir)/
	rsync -a $(env_file) $(ssh_host):$(remote_dir)/$(env_file)
endif

.PHONY: deploy-build
deploy-build: deploy-validate
	$(call RUN,$(compose_cmd) build)

.PHONY: deploy-up
deploy-up: deploy-validate
	$(call RUN,$(compose_cmd) up -d)

.PHONY: deploy-down
deploy-down: deploy-validate
	$(call RUN,$(compose_cmd) down)

.PHONY: deploy-restart
deploy-restart: deploy-validate
	$(call RUN,$(compose_cmd) restart)

.PHONY: deploy-ps
deploy-ps: deploy-validate
	$(call RUN,$(compose_cmd) ps)

.PHONY: deploy-logs
deploy-logs: deploy-validate
	$(call RUN,$(compose_cmd) logs -f --tail=200)

.PHONY: deploy-config
deploy-config: deploy-validate
	$(call RUN,$(compose_cmd) config)

# The image entrypoint is `python -m`, so the command is the module and its args.
.PHONY: deploy-migrate
deploy-migrate: deploy-validate
	$(call RUN,$(compose_cmd) run --rm api alembic upgrade head)

.PHONY: deploy-seed
deploy-seed: deploy-validate
	$(call RUN,$(compose_cmd) run --rm api cmd.seed_role_models)

# Runs from here in both cases: it is an HTTP client, not a container.
.PHONY: deploy-smoke
deploy-smoke: deploy-validate
	API_BASE=$(if $(filter production,$(env)),$(shell sed -n 's/^PUBLIC_BASE_URL=//p' $(env_file)),http://127.0.0.1:8000) \
		bash scripts/smoke.sh
