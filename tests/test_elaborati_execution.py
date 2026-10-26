"""Shared time boundaries and the real response serializer; no database writes."""
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from edilcloud.modules.elaborati import services

_fixture = json.loads((Path(__file__).parent / 'fixtures/elaborati-execution.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', _fixture['cases'], ids=lambda case: case['name'])
def test_execution_observation_does_not_change_job_or_retry_policy(case, monkeypatch):
    now = datetime.fromisoformat(_fixture['now'])
    monkeypatch.setattr(services.timezone, 'now', lambda: now)
    job = SimpleNamespace(
        pk=uuid.uuid4(), revision_id=uuid.uuid4(), state=case['state'], stage='rendering',
        action='preview', input_version=3, error_code='', error_message='', result={},
        workflow_state={}, workflow_version='v1',
        created_at=now - timedelta(milliseconds=case['created_age_ms']),
        lease_expires_at=None if case['lease_offset_ms'] is None else now + timedelta(milliseconds=case['lease_offset_ms']),
    )
    before = vars(job).copy()
    result = services.serialize_job(job)
    assert result['execution_status'] == case['expected']
    assert result['state'] == case['state']
    assert result['result'] is None and result['can_resume'] is False
    assert vars(job) == before
