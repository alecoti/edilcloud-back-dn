"""Focused adoption gates; real fresh-runner transitions have a separate harness."""
import hashlib
from io import StringIO
import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from edilcloud.modules.projects.models import ProjectActivity, ProjectTask
from edilcloud.modules.projects.shared_schema import (
    NATIVE_PHASE, NATIVE_PHASE_CHECKSUM, PHASE, record_verified_phase, verified_phase_adoption,
)

from tests.test_elaborati import site  # shared fixture

pytestmark = [pytest.mark.django_db, pytest.mark.skipif(
    connection.vendor != 'postgresql', reason='PostgreSQL adoption catalog checks')]


@pytest.fixture
def native_receipt():
    # The test schema was created by Django. Model the native receipt explicitly;
    # this fixture is not evidence of a full native bootstrap.
    resource = Path(__file__).resolve().parent / 'fixtures/native-phase-staffing-2026101901.sql'
    assert hashlib.sha384(resource.read_bytes()).hexdigest() == NATIVE_PHASE_CHECKSUM
    with connection.cursor() as cursor:
        cursor.execute('CREATE TABLE _sqlx_migrations (version bigint PRIMARY KEY, checksum bytea NOT NULL, success boolean NOT NULL)')
        cursor.execute('INSERT INTO _sqlx_migrations VALUES (%s,%s,true)',
                       [NATIVE_PHASE, bytes.fromhex(NATIVE_PHASE_CHECKSUM)])
    loader = MigrationLoader(connection)
    pending = loader.graph.backwards_plan(PHASE)
    recorder = MigrationRecorder(connection)
    # A historical receipt gap cannot leave later dependencies marked applied.
    # Tables stay in the current test schema; full native bootstrap is a separate gate.
    for key in pending:
        recorder.record_unapplied(*key)
    return pending


def recorded():
    return PHASE in MigrationRecorder(connection).applied_migrations()


def test_plan_is_read_only_and_apply_preserves_later_staffing_choices(native_receipt, site):
    project, _, worker, *_ = site
    now = timezone.now()
    task = ProjectTask.objects.create(project=project, name='Existing phase',
                                     date_start=now.date(), date_end=now.date())
    activity = ProjectActivity.objects.create(task=task, title='Later user choice',
                                             datetime_start=now, datetime_end=now,
                                             inherit_workers=True)
    activity.workers.add(worker)
    task.workers.add(worker)
    output = StringIO()
    call_command('migrate_shared', stdout=output, verbosity=0)
    assert json.loads(output.getvalue())['phase_adoption'] is True
    assert not recorded()
    with transaction.atomic():
        assert record_verified_phase(connection) is True
    # Descendants were genuinely installed by the test database bootstrap.
    # Restore only their receipts so the current-version command can verify
    # its no-op tail without replaying later irreversible audit migrations.
    for key in reversed(native_receipt):
        if key != PHASE:
            MigrationRecorder(connection).record_applied(*key)
    output = StringIO()
    call_command('migrate_shared', apply=True, stdout=output, verbosity=0)
    assert json.loads(output.getvalue())['remaining'] == []
    assert recorded()
    activity.refresh_from_db()
    # Replaying RunPython would silently reset this later choice to False.
    assert activity.inherit_workers is True
    assert list(activity.workers.values_list('id', flat=True)) == [worker.id]
    assert list(task.workers.values_list('id', flat=True)) == [worker.id]
    with transaction.atomic():
        assert record_verified_phase(connection) is False


@pytest.mark.parametrize('drift', ['type', 'nullable', 'unique', 'checksum', 'failed_receipt', 'extra_check', 'extra_unique'])
def test_drift_never_records_unexecuted_history(native_receipt, drift):
    with connection.cursor() as cursor:
        if drift == 'type':
            cursor.execute('ALTER TABLE projects_projectactivity ALTER COLUMN inherit_workers TYPE text')
        elif drift == 'nullable':
            cursor.execute('ALTER TABLE projects_projectactivity ALTER COLUMN inherit_workers DROP NOT NULL')
        elif drift == 'unique':
            cursor.execute("SELECT conname FROM pg_constraint WHERE conrelid='projects_projecttask_workers'::regclass AND contype='u'")
            name = cursor.fetchone()[0]
            cursor.execute('ALTER TABLE projects_projecttask_workers DROP CONSTRAINT ' + connection.ops.quote_name(name))
        elif drift == 'checksum':
            cursor.execute("UPDATE _sqlx_migrations SET checksum=decode('00','hex')")
        elif drift == 'extra_check':
            cursor.execute('ALTER TABLE projects_projecttask_workers ADD CONSTRAINT owned_extra CHECK(profile_id>1000)')
        elif drift == 'extra_unique':
            cursor.execute('CREATE UNIQUE INDEX owned_extra_unique ON projects_projecttask_workers(projecttask_id)')
        else:
            cursor.execute('UPDATE _sqlx_migrations SET success=false')
    with pytest.raises(CommandError, match='no history adopted'):
        with transaction.atomic():
            record_verified_phase(connection)
    assert not recorded()


def test_reference_to_same_table_name_in_another_schema_is_rejected(native_receipt):
    with connection.cursor() as cursor:
        cursor.execute('CREATE SCHEMA shared_wrong')
        cursor.execute('CREATE TABLE shared_wrong.workspaces_profile (id bigint PRIMARY KEY)')
        cursor.execute("SELECT conname FROM pg_constraint WHERE conrelid='projects_projecttask_workers'::regclass AND contype='f' AND confrelid='public.workspaces_profile'::regclass")
        name = cursor.fetchone()[0]
        cursor.execute('ALTER TABLE projects_projecttask_workers DROP CONSTRAINT ' + connection.ops.quote_name(name))
        cursor.execute('ALTER TABLE projects_projecttask_workers ADD FOREIGN KEY(profile_id) '
                       'REFERENCES shared_wrong.workspaces_profile(id) DEFERRABLE INITIALLY DEFERRED')
    with pytest.raises(CommandError, match='keys/references'):
        verified_phase_adoption(connection)
    assert not recorded()
