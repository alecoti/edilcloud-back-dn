"""Verify a known native phase migration before adopting its Django history.

No application rows are backfilled again. The original native transaction has
already preserved historical explicit staffing; replaying it would reset later
user choices. A matching receipt AND the actual schema are both required.
"""
from django.core.management.base import CommandError
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

SHARED_MIGRATION_LOCK = 2026102602
PHASE = ('projects', '0028_phase_staff_inheritance')
NATIVE_PHASE = 2026101901
NATIVE_PHASE_CHECKSUM = (
    '438dbbc9ad08f46be707793601a25df4a8ee68327a92e00b232af62c33da106d358051d965248325d04b72747586592c'
)


def _require(condition, detail):
    if not condition:
        raise CommandError(f'Incompatible shared phase schema: {detail}; no history adopted.')


def verified_phase_adoption(connection):
    """Read-only validation, also used by the command's default plan mode."""
    loader = MigrationLoader(connection)
    loader.check_consistent_history(connection)
    applied = set(loader.applied_migrations)
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public._sqlx_migrations') IS NOT NULL")
        if not cursor.fetchone()[0]:
            return False
        cursor.execute(
            "SELECT success,encode(checksum,'hex') FROM public._sqlx_migrations WHERE version=%s",
            [NATIVE_PHASE],
        )
        receipt = cursor.fetchone()
        if receipt is None:
            return False
        _require(receipt == (True, NATIVE_PHASE_CHECKSUM), 'native receipt/checksum')
        migration = loader.disk_migrations[PHASE]
        _require(all(key in applied for key in migration.dependencies), 'Django dependencies')
        cursor.execute("""
            SELECT format_type(a.atttypid,a.atttypmod),a.attnotnull,pg_get_expr(d.adbin,d.adrelid)
            FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
            WHERE a.attrelid=to_regclass('public.projects_projectactivity')
                AND a.attname='inherit_workers' AND NOT a.attisdropped
        """)
        _require(cursor.fetchone() == ('boolean', True, None), 'inherit_workers column')
        cursor.execute("""
            SELECT a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity
            FROM pg_attribute a WHERE a.attrelid=to_regclass('public.projects_projecttask_workers')
                AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attname
        """)
        _require(cursor.fetchall() == [
            ('id', 'bigint', True, 'd'), ('profile_id', 'bigint', True, ''),
            ('projecttask_id', 'bigint', True, ''),
        ], 'phase worker columns')
        cursor.execute("""
            SELECT k.contype::text,
                ARRAY(SELECT a.attname::text FROM unnest(k.conkey) WITH ORDINALITY c(n,pos)
                    JOIN pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=c.n ORDER BY c.pos),
                coalesce(ref.relname,''),
                ARRAY(SELECT a.attname::text FROM unnest(k.confkey) WITH ORDINALITY c(n,pos)
                    JOIN pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=c.n ORDER BY c.pos),
                k.condeferrable,k.condeferred,k.convalidated,k.confupdtype::text,k.confdeltype::text,
                CASE WHEN k.contype IN ('p','u') THEN
                    ix.indisvalid AND ix.indisready AND ix.indisunique
                    AND ix.indpred IS NULL AND ix.indexprs IS NULL ELSE true END,
                CASE WHEN k.contype='f' THEN refns.nspname='public' ELSE true END
            FROM pg_constraint k LEFT JOIN pg_class ref ON ref.oid=k.confrelid
                LEFT JOIN pg_namespace refns ON refns.oid=ref.relnamespace
                LEFT JOIN pg_index ix ON ix.indexrelid=k.conindid
            WHERE k.conrelid=to_regclass('public.projects_projecttask_workers')
                AND k.contype<>'n'
        """)
        constraints = cursor.fetchall()
        expected = [
            ('p', ['id'], '', [], False, False, True, ' ', ' ', True, True),
            ('u', ['projecttask_id', 'profile_id'], '', [], False, False, True, ' ', ' ', True, True),
            ('f', ['projecttask_id'], 'projects_projecttask', ['id'], True, True, True, 'a', 'a', True, True),
            ('f', ['profile_id'], 'workspaces_profile', ['id'], True, True, True, 'a', 'a', True, True),
        ]
        _require(len(constraints) == len(expected) and all(row in constraints for row in expected),
                 'phase worker keys/references')
        cursor.execute("SELECT count(*) FROM pg_index WHERE "
                       "indrelid=to_regclass('public.projects_projecttask_workers') AND indisunique")
        _require(cursor.fetchone()[0] == 2, 'additional unique phase worker index')
    return PHASE not in applied


def record_verified_phase(connection):
    """Call inside an atomic block while holding the shared migration lock."""
    # Block writes for the schema check and history commit. Names are fixed.
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.projects_projecttask_workers') IS NOT NULL")
        if cursor.fetchone()[0]:
            cursor.execute('LOCK TABLE public.projects_projecttask_workers, '
                           'public.projects_projectactivity IN SHARE MODE')
    if not verified_phase_adoption(connection):
        return False
    MigrationRecorder(connection).record_applied(*PHASE)
    return True
