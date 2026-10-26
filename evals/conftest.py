import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # DATA_DIR and web/dist are relative to the repo root

GOLDEN = json.loads((Path(__file__).parent / "golden.json").read_text())["cases"]


def cases(*categories):
    return [c for c in GOLDEN if c["category"] in categories]


@pytest.fixture(scope="session")
def index():
    from app import index as idx

    idx.load()
    return idx
