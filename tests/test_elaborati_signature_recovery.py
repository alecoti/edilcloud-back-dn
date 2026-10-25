import pytest
from ninja.errors import HttpError

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.models import PersonalSignature
from tests.test_elaborati import site  # noqa: F401

pytestmark = pytest.mark.django_db
STROKES = [[[0, 0], [0.2, 0.3], [0.4, 0.2], [0.9, 0.7]]]


@pytest.mark.parametrize("count", [2, 3, 8001])
def test_signature_point_limits_remain_authoritative(site, count):
    with pytest.raises(HttpError) as error:
        services.save_signature(user=site[1].user, strokes=[[[0.2, 0.3]] * count])
    assert error.value.status_code == 400
    assert not PersonalSignature.objects.filter(user=site[1].user).exists()


def test_replacing_signature_survives_post_commit_cleanup_failure(
    site, monkeypatch, django_capture_on_commit_callbacks
):
    old = services.save_signature(user=site[1].user, strokes=STROKES)
    old_name = old.image.name
    deleted = []

    def unavailable(name):
        deleted.append(name)
        raise OSError("synthetic signature cleanup failure")

    monkeypatch.setattr(old.image.storage, "delete", unavailable)
    replacement = [[[0.1, 0.1], [0.3, 0.5], [0.5, 0.1], [0.8, 0.8]]]
    with django_capture_on_commit_callbacks(execute=True):
        current = services.save_signature(user=site[1].user, strokes=replacement)

    current.refresh_from_db()
    assert current.strokes == replacement
    assert current.image.name != old_name
    assert deleted == [old_name]
    assert current.image.storage.exists(current.image.name)


def test_deleting_signature_survives_cleanup_failure_and_is_personal(
    site, monkeypatch, django_capture_on_commit_callbacks
):
    own = services.save_signature(user=site[1].user, strokes=STROKES)
    other = services.save_signature(user=site[2].user, strokes=STROKES)

    deleted = []

    def unavailable(name):
        deleted.append(name)
        raise OSError("synthetic deletion cleanup failure")

    monkeypatch.setattr(own.image.storage, "delete", unavailable)
    with django_capture_on_commit_callbacks(execute=True):
        services.delete_signature(user=site[1].user)
    assert not PersonalSignature.objects.filter(user=site[1].user).exists()
    assert PersonalSignature.objects.filter(pk=other.pk).exists()
    assert deleted == [own.image.name]
    services.delete_signature(user=site[1].user)  # A retry remains a success.
    assert deleted == [own.image.name]
