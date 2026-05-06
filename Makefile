UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv run
SMOKE_ARGS ?= smoke -n 0 -s --tb=short
SMOKE_PRODUCT_ARGS ?= smoke/product -n 0 -s --tb=short

.PHONY: format lint ty test ci smoke-collect smoke-live smoke-targets

format:
	$(UV) ruff format

lint:
	$(UV) ruff check

ty:
	$(UV) ty check

test:
	$(UV) pytest

ci: format lint ty test

smoke-collect:
	$(UV) pytest smoke --collect-only -q

smoke-live:
	FCC_LIVE_SMOKE=1 $(UV) pytest $(SMOKE_ARGS)

smoke-targets:
	FCC_LIVE_SMOKE=1 $(UV) pytest $(SMOKE_PRODUCT_ARGS)
