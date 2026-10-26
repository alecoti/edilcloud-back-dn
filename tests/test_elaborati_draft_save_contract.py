"""Shared client/backend rules for conservative save receipt reconciliation."""
import json
from pathlib import Path

import pytest
from edilcloud.modules.elaborati.content import editor_equivalent

_fixture=json.loads((Path(__file__).parent/'fixtures/elaborati-draft-save.json').read_text())

@pytest.mark.parametrize('case',_fixture['equivalence'],ids=lambda case:case['name'])
def test_save_receipt_equivalence_matches_server(case):
    assert editor_equivalent(case['left'],case['right']) is case['expected']
