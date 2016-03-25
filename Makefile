.PHONY: help clean check-stage pipme require lint test tox register upload release sdist wheel

help:
	@echo "clean - remove Python file and build artifacts"
	@echo "check-stage - check staged changes for lint errors"
	@echo "pipme - install requirements.txt"
	@echo "require - create requirements.txt"
	@echo "lint - check style with flake8"
	@echo "test - run nose and script tests"
	@echo "release - package and upload a release"
	@echo "sdist - create a source distribution package"
	@echo "wheel - create a wheel package"
	@echo "upload - upload dist files"
	@echo "register - register package with PyPI"
	@echo "tox - run tests on every Python version with tox"

clean:
	helpers/clean

check-stage:
	helpers/check-stage

pipme:
	pip install -r requirements.txt

require:
	pip freeze -l | grep -vxFf dev-requirements.txt > requirements.txt

lint:
	flake8 meza tests

test:
	nosetests -xv
	python tests/test.py

release: clean sdist wheel upload

register:
	python setup.py register

sdist:
	clean
	helpers/srcdist

wheel:
	clean
	helpers/wheel

upload:
	twine upload dist/*

tox:
	tox
