.PHONY: test run check

test:
	python -m unittest discover -s tests -p "test_*.py" -v

check:
	python -m compileall -q src tests
	python -m unittest discover -s tests -p "test_*.py" -v

run:
	python -m jarvis_omega.main
