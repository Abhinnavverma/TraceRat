.PHONY: build up down restart logs test lint clean

# Build all services
build:
	docker-compose build

# Start all services
up:
	docker-compose up -d

# Start with build
up-build:
	docker-compose up -d --build

# Stop all services
down:
	docker-compose down

# Stop and remove volumes
down-clean:
	docker-compose down -v

# Restart all services
restart:
	docker-compose restart

# View logs
logs:
	docker-compose logs -f

# View logs for a specific service
logs-%:
	docker-compose logs -f $*

# Run api-gateway tests
test-api-gateway:
	cd api-gateway && python -m pytest tests/ -v

# Run all tests
test:
	$(MAKE) test-api-gateway

# Lint all services
lint:
	cd api-gateway && python -m ruff check .

# Format code
format:
	cd api-gateway && python -m ruff format .

# Clean up
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
