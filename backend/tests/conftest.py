import os
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="jobagent-test-")
os.environ["JOBAGENT_DATA_DIR"] = _tmp
os.environ["JOBAGENT_SCHEDULER_ENABLED"] = "false"


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return Path(_tmp)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from jobagent.main import app

    with TestClient(app) as c:
        yield c
