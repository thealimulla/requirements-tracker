import json
from pathlib import Path

import pytest

from req_tracker.config import load_config

ROOT = Path(__file__).parent.parent
SAMPLE = ROOT / "examples" / "sample_data"


@pytest.fixture
def cfg():
    return load_config(ROOT / "examples" / "tracker.toml")


@pytest.fixture
def sample():
    def load(name):
        return json.loads((SAMPLE / f"{name}.json").read_text())
    return load
