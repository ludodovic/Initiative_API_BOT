COMPOSE := docker compose -f docker-compose.dev.yml

.PHONY: help up seed dev logs down clean

help:
	@echo "make dev   Start the local API"
	@echo "make up    Build"
	@echo "make logs  Follow local API and MongoDB logs"
	@echo "make down  Stop the local stack"
	@echo "make clean Stop the stack and delete local MongoDB data"

up:
	$(COMPOSE) up --build

dev: up

logs:
	$(COMPOSE) logs --follow api mongo

down:
	$(COMPOSE) down

clean:
	$(COMPOSE) down --volumes
