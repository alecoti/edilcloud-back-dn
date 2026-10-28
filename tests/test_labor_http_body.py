"""Exercise Ninja binding of the real handlers, separately from persistence/auth."""
from types import SimpleNamespace
from uuid import UUID

import pytest
from ninja import Router
from ninja.testing import TestClient

from edilcloud.modules.elaborati import api, labor_api, labor_proposals
from edilcloud.modules.projects import services as projects


@pytest.fixture(params=['preview', 'identity', 'create', 'command', 'interpret'])
def endpoint(request, monkeypatch):
    actor = SimpleNamespace(workspace_id=1)
    monkeypatch.setattr(api, 'profile_for', lambda request: actor)
    monkeypatch.setattr(labor_api, 'profile', lambda request: actor)
    def echo(profile, body):
        return {'received': body}
    monkeypatch.setattr(labor_api.ledger, 'create_identity', echo)
    monkeypatch.setattr(labor_api.ledger, 'create_register', echo)
    monkeypatch.setattr(labor_api.ledger, 'command', lambda profile, register_id, body: {'received': body, 'id': str(register_id)})
    monkeypatch.setattr(labor_api.interpretations, 'interpret', echo)
    monkeypatch.setattr(labor_proposals, 'labor_proposal', lambda body: {'received': body})
    monkeypatch.setattr(projects, 'get_project_for_profile', lambda **kwargs: object())
    monkeypatch.setattr(projects, 'get_project_membership', lambda project, profile: None)
    handlers = {
        'preview': ('/preview', api.preview_labor_proposal),
        'identity': ('/identities', labor_api.create_identity),
        'create': ('/registers', labor_api.create),
        'command': ('/registers/{register_id}/commands', labor_api.command),
        'interpret': ('/interpretations', labor_api.interpret),
    }
    path, handler = handlers[request.param]
    router = Router()
    router.post(path)(handler)
    return TestClient(router), path.replace('{register_id}', str(UUID(int=1)))


def test_json_object_reaches_handler_without_a_query_payload(endpoint):
    client, path = endpoint
    payload = {'project_id': 1, 'source': {'text': 'QA 7 ore e mezza'}, 'rows': [{'minutes': 450}]}
    response = client.post(path + '?payload=ignored', json=payload)
    assert response.status_code == 200
    assert response.json()['received'] == payload
    assert response.headers['Cache-Control'] == 'private, no-store'


def test_query_payload_cannot_replace_the_required_json_body(endpoint):
    client, path = endpoint
    response = client.post(path + '?payload=%7B%22project_id%22%3A1%7D')
    assert response.status_code == 422
    assert all(item['loc'][0] == 'body' for item in response.json()['detail'])
