Pytest-Thread: A plugin For Concurrent Testing
============================================================

pytest-thread is cloning base code with [pytest-parallel](https://github.com/kevlened/pytest-parallel/tree/0.1.1) to fix
error: `AttributeError: Can't pickle local object 'ArgumentParser.__init__.<locals>.identity'` 
when `platform is windows && python version > 3.8 && pytest-parallel == 0.1.1`

Also remove multiple processing and keep multiple threading only.

Installation
============

Poetry Example: 
```
1. clonning to your project

2. dependecies set up
[tool.poetry.dependencies]
**
**
pytest-thread = {path="./pytest-thread"}

3. poetry lock --no-update && poetry install --sync
```

Manually Register Code Example:
```
1. clonning to your project

2. add `pytest_plugins = ["pytest-thread.src.pytest_thread.plugins"]` into
 conftest.py

OR

3. pytest command line with ``PYTEST_PLUGINS`` env variable
```

Pytest Options:
`--worker=auto or --worker={number}`

