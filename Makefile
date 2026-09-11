COMPOSE_BIN := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")
COMPOSE := $(COMPOSE_BIN) -f docker-compose.yml

.PHONY: help build up update logs status down reset

help:
	@echo "make up      Build and start the application"
	@echo "make update  Pull code, rebuild, and redeploy the application"
	@echo "make logs    Follow application logs"
	@echo "make status  Show container status"
	@echo "make down    Stop the application (persistent uploads are kept)"
	@echo "make reset   Stop the application and DELETE persistent uploads"

build:
	$(COMPOSE) build --pull api

up: build
	$(COMPOSE) up --detach --remove-orphans

update:
	git pull --ff-only
	$(COMPOSE) build --pull api
	$(COMPOSE) up --detach --remove-orphans
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs --follow api

status:
	$(COMPOSE) ps

down:
	$(COMPOSE) down

reset:
	@echo "WARNING: this deletes all persisted claim images and profile pictures."
	$(COMPOSE) down --volumes
