import os

import py
import sys
import pytest
import _pytest
import threading
import queue

__version__ = "0.0.1"


def parse_config(config, name):
    return getattr(config.option, name, config.getini(name))


def pytest_addoption(parser):
    workers_help = "Set the max num of workers (aka processes) to start " '(int or "auto" - one per core)'

    group = parser.getgroup("pytest-parallel")
    group.addoption("--workers", dest="workers", help=workers_help)
    parser.addini("workers", workers_help)


def run_test(session, item, nextitem):
    item.ihook.pytest_runtest_protocol(item=item, nextitem=nextitem)
    if session.shouldstop:
        raise session.Interrupted(session.shouldstop)


class ThreadWorker(threading.Thread):
    def __init__(self, queue, session, errors):
        super().__init__()
        self.queue = queue
        self.session = session
        self.errors = errors
        self.daemon = True

    def run(self):
        while True:
            try:
                index = self.queue.get(timeout=0.5)
            except queue.Empty:
                if self.queue.empty():
                    break
                continue
            except Exception as e:
                self.errors.put((self.name, e))
                break
            else:
                try:
                    if index == "stop":
                        break
                    item = self.session.items[index]
                    run_test(self.session, item, None)
                except BaseException as e:
                    self.errors.put((self.name, e))
                finally:
                    self.queue.task_done()


@pytest.mark.trylast
def pytest_configure(config):
    workers = parse_config(config, "workers")
    if not config.option.collectonly and workers:
        config.pluginmanager.register(ThreadRunner(config), "parallelrunner")


class ThreadLocalEnviron(os._Environ):
    def __init__(self, env):
        if sys.version_info >= (3, 9):
            super().__init__(
                env._data,
                env.encodekey,
                env.decodekey,
                env.encodevalue,
                env.decodevalue,
            )
            self.putenv = os.putenv
            self.unsetenv = os.unsetenv
        else:
            super().__init__(
                env._data, env.encodekey, env.decodekey, env.encodevalue, env.decodevalue, env.putenv, env.unsetenv
            )
        self.thread_store = threading.local()

    def __getitem__(self, key):
        if key == "PYTEST_CURRENT_TEST":
            return getattr(self.thread_store, key)
        else:
            # 确保 key 是字符串类型
            if isinstance(key, bytes):
                key = self.decodekey(key)
            return super().__getitem__(key)

    def __setitem__(self, key, value):
        if key == "PYTEST_CURRENT_TEST":
            setattr(self.thread_store, key, value)
        else:
            if isinstance(key, bytes):
                key = self.decodekey(key)
            super().__setitem__(key, value)

    def __delitem__(self, key):
        if key == "PYTEST_CURRENT_TEST":
            if hasattr(self.thread_store, key):
                delattr(self.thread_store, key)
        else:
            if isinstance(key, bytes):
                key = self.decodekey(key)
            super().__delitem__(key)

    def __contains__(self, key):
        if key == "PYTEST_CURRENT_TEST":
            return hasattr(self.thread_store, key)
        else:
            # 显式将 key 转换为字符串类型
            if isinstance(key, bytes):
                key = self.decodekey(key)
            return super().__contains__(key)

    def __iter__(self):
        keys = list(super().__iter__())
        if hasattr(self.thread_store, "PYTEST_CURRENT_TEST"):
            keys.append("PYTEST_CURRENT_TEST")
        return iter(keys)

    def __len__(self):
        return super().__len__() + (1 if hasattr(self.thread_store, "PYTEST_CURRENT_TEST") else 0)

    def copy(self):
        new_env = ThreadLocalEnviron(self)
        new_env.thread_store.__dict__.update(self.thread_store.__dict__)
        return new_env


class ThreadLocalSetupState(threading.local, _pytest.runner.SetupState):
    def __init__(self):
        super().__init__()


class ThreadLocalFixtureDef(threading.local, _pytest.fixtures.FixtureDef):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class ThreadRunner:
    def __init__(self, config):
        self._config = config
        self._log = py.log.Producer("pytest-thread")

        reporter = config.pluginmanager.getplugin("terminalreporter")
        reporter.showfspath = False
        reporter._show_progress_info = False

        workers = parse_config(config, "workers")
        if workers == "auto":
            workers = os.cpu_count() or 1
        else:
            workers = int(workers)
        self.workers = workers

    @pytest.mark.tryfirst
    def pytest_sessionstart(self, session):
        _pytest.runner.SetupState = ThreadLocalSetupState
        _pytest.fixtures.FixtureDef = ThreadLocalFixtureDef
        os.environ = ThreadLocalEnviron(os.environ)

    def pytest_runtestloop(self, session):
        if session.testsfailed and not session.config.option.continue_on_collection_errors:
            raise session.Interrupted(
                f"{session.testsfailed} error{'s' if session.testsfailed != 1 else ''} during collection"
            )

        if session.config.option.collectonly:
            return True

        test_queue = queue.Queue()
        error_queue = queue.Queue()

        for i in range(len(session.items)):
            test_queue.put(i)
        for _ in range(self.workers):
            test_queue.put("stop")

        threads = []
        for _ in range(self.workers):
            thread = ThreadWorker(test_queue, session, error_queue)
            thread.start()
            threads.append(thread)

        test_queue.join()
        for t in threads:
            t.join(timeout=1)

        if not error_queue.empty():
            errors = []
            while not error_queue.empty():
                thread_name, error = error_queue.get()
                errors.append(f"{thread_name}: {error}")
            raise RuntimeError("Errors occurred:\n" + "\n".join(errors))

        return True
