COMPOSE := docker compose -f docker-compose.dev.yml

.PHONY: help up seed dev logs down clean

help:
	@echo "make dev   Start the local API and MongoDB, then seed fixture users"
	@echo "make up    Start the local API and MongoDB"
	@echo "make seed  Seed local fixture users"
	@echo "make logs  Follow local API and MongoDB logs"
	@echo "make down  Stop the local stack"
	@echo "make clean Stop the stack and delete local MongoDB data"

up:
	$(COMPOSE) up --build --detach

seed: up
	$(COMPOSE) exec api python -m app.scripts.seed_local_data

dev: seed

logs:
	$(COMPOSE) logs --follow api mongo

down:
	$(COMPOSE) down

clean:
	$(COMPOSE) down --volumes
