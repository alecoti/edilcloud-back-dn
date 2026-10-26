"""Coordinate Django upgrades with validated adoption of known native DDL."""
import json

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.db.migrations.executor import MigrationExecutor

from edilcloud.modules.projects.shared_schema import (
    NATIVE_PHASE, PHASE, SHARED_MIGRATION_LOCK, record_verified_phase, verified_phase_adoption,
)


class Command(BaseCommand):
    help = 'Piano dello schema condiviso; --apply verifica/adotta il DDL nativo noto e migra Django.'

    def add_arguments(self, parser):
        parser.add_argument('--database', default='default')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        connection = connections[options['database']]
        if connection.vendor != 'postgresql':
            raise CommandError('Shared schema adoption requires PostgreSQL.')
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_schema()')
            if cursor.fetchone()[0] != 'public':
                raise CommandError('Shared migrations require search_path to resolve public.')
            cursor.execute('SELECT pg_advisory_lock(%s)', [SHARED_MIGRATION_LOCK])
        try:
            adopt = verified_phase_adoption(connection)
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            report = {'applied': options['apply'], 'phase_adoption': adopt,
                      'native_receipt': NATIVE_PHASE if adopt else None,
                      'pending': [f'{migration.app_label}.{migration.name}' for migration, _ in plan]}
            if options['apply']:
                with transaction.atomic(using=connection.alias):
                    report['phase_adoption'] = record_verified_phase(connection)
                call_command('migrate', database=connection.alias, interactive=False,
                             verbosity=options['verbosity'], stdout=self.stdout, stderr=self.stderr)
                executor = MigrationExecutor(connection)
                _remaining = executor.migration_plan(executor.loader.graph.leaf_nodes())
                if _remaining:
                    raise CommandError('Shared migration left pending operations.')
                report['remaining'] = []
                report['adopted'] = '.'.join(PHASE) if report['phase_adoption'] else None
            self.stdout.write(json.dumps(report))
        finally:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [SHARED_MIGRATION_LOCK])
