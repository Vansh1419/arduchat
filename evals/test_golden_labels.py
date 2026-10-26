"""The golden set must agree with the indexed docs, otherwise the other evals measure nothing."""
import re

import pytest

from conftest import cases

PARAM_LIKE = re.compile(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+$")


@pytest.mark.parametrize("case", cases("in_scope", "follow_up"), ids=lambda c: c["id"])
def test_labels_exist_in_index(index, case):
    pages = {}
    for c in index.chunks:
        pages.setdefault(c["url"].rsplit("/", 1)[-1], []).append(c["text"])
    missing = [u for u in case["expected_urls"] if u not in pages]
    assert not missing, f"expected pages not in the index: {missing}"

    text = "\n".join(t for u in case["expected_urls"] for t in pages[u])
    for token in case["must_mention"]:
        found = token in text if PARAM_LIKE.match(token) else token.lower() in text.lower()
        assert found, f"'{token}' does not appear in any expected page"
