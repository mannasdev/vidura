# Vidura — one-command setup (the "stranger in 10 minutes" criterion)
.PHONY: install test test-pet report sweep app

install:
	python3.11 -m venv .venv || python3 -m venv .venv
	.venv/bin/pip install -q -e ".[dev]"
	@echo "✓ installed. Try: .venv/bin/vidura-report  (needs Claude Code)"

test:
	.venv/bin/pytest -q
	$(MAKE) test-pet

test-pet:
	cd pet && swift test

report:
	.venv/bin/vidura-report

sweep:
	.venv/bin/vidura-sweep

# assembles the downloadable unsigned Vidura.app
app:
	bash pet/scripts/make-app.sh
	@echo "✓ built Vidura.app → pet/dist/Vidura.app"
