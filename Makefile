.PHONY: test run check

test:
	uv run --locked python -m unittest discover -s tests -p "test_*.py" -v

check:
	uv run --locked python -m compileall -q src tests
	uv run --locked python -m unittest discover -s tests -p "test_*.py" -v

run:
	uv run --locked my-last-ai-girlfriends
