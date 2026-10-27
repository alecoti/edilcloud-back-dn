"""Explicit maintenance command; no rollout side effect in migrations/startup."""

from django.apps import apps
from django.conf import settings
from django.db import connection, models, transaction

from edilcloud.modules.projects.document_storage import is_publication_name, publication_revision
from edilcloud.modules.projects.models import ProjectDocument
from .models import DocumentAudit, ElaboratoRevision
from .publication_transfer import PublicationTransfer, TransferBlocked

ACTION = "storage_privatized"
RETIRED_ACTION = "storage_public_retired"


def other_reference(name, document_id):
    """Conservative exact text reference check; never infer exclusive ownership.

    PostgreSQL also covers native runtime tables not represented by Django models.
    JSON snapshots are deliberately immutable history, not live file-field owners.
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT n.nspname,c.relname,a.attname FROM pg_attribute a
                JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_type t ON t.oid=a.atttypid
                WHERE n.nspname IN ('public','edilcloud_runtime') AND c.relkind IN ('r','p')
                AND a.attnum>0 AND NOT a.attisdropped AND t.typname IN ('text','varchar')
                ORDER BY n.nspname,c.relname,a.attname
            """)
            queries = []
            for schema, table, column in cursor.fetchall():
                q = connection.ops.quote_name
                sql = f"SELECT 1 FROM {q(schema)}.{q(table)} WHERE {q(column)}=%(name)s"
                if (schema, table, column) == ("public", "projects_projectdocument", "document"):
                    sql += " AND id<>%(document_id)s"
                queries.append(sql)
            for offset in range(0, len(queries), 64):
                sql = "SELECT EXISTS(" + " UNION ALL ".join(queries[offset : offset + 64]) + ")"
                cursor.execute(sql, {"name": name, "document_id": document_id})
                if cursor.fetchone()[0]:
                    return True
        return False
    for model in apps.get_models():
        for field in model._meta.concrete_fields:
            if isinstance(field, models.FileField):
                query = model._base_manager.filter(**{field.name: name})
                if model is ProjectDocument and field.name == "document":
                    query = query.exclude(pk=document_id)
                if query.exists():
                    return True
    return False


def transfer_revision(revision_id, *, apply=False, maintenance=False):
    if apply and not maintenance:
        raise ValueError(
            "L'applicazione richiede --maintenance: API e worker devono essere arrestati."
        )
    if apply and connection.in_atomic_block:
        raise ValueError("Il trasferimento deve poter confermare la propria transazione DB.")
    result = {"revision_id": str(revision_id), "status": "blocked"}
    try:
        transfer = PublicationTransfer(settings.MEDIA_ROOT, settings.PRIVATE_STORAGE_ROOT)
        with transaction.atomic():
            revision = (
                ElaboratoRevision.objects.select_for_update()
                .select_related("elaborato")
                .get(pk=revision_id)
            )
            if (
                revision.state not in ("published", "signed", "superseded")
                or not revision.drive_document_id
            ):
                raise TransferBlocked("not_issued")
            document = ProjectDocument.objects.select_for_update().get(
                pk=revision.drive_document_id
            )
            if document.project_id != revision.elaborato.project_id:
                raise TransferBlocked("project_mismatch")
            current = document.document.name
            audit = (
                DocumentAudit.objects.filter(revision=revision, action=ACTION)
                .order_by("id")
                .first()
            )
            target = (
                current
                if is_publication_name(current)
                else (f"elaborati/publications/{revision.pk.hex}-{document.pk:032x}.pdf")
            )
            if publication_revision(target) != revision.pk:
                raise TransferBlocked("publication_revision_mismatch")
            old = current
            retired = f"elaborati/public-retired/{revision.pk.hex}-{document.pk:032x}.pdf"
            detail = {
                "schema_version": 1,
                "drive_document_id": document.pk,
                "old_name": old,
                "new_name": target,
                "retired_name": retired,
                "sha256": revision.pdf_hash,
                "byte_length": document.file_size,
            }
            if audit:
                old = audit.detail.get("old_name")
                detail["old_name"] = old
                if not isinstance(old, str) or audit.detail != detail or current != target:
                    raise TransferBlocked("migration_audit_mismatch")
            if other_reference(old, document.pk) or (
                target != old and other_reference(target, document.pk)
            ):
                raise TransferBlocked("shared_file_reference")
            state = transfer.inspect(old, target, retired, revision.pdf_hash, document.file_size)
            result.update({**detail, **state})
            needed = audit is not None or state["public_present"] or current != target
            if not needed:
                result["status"] = "already_private"
                return result
            if not apply:
                result["status"] = "ready"
                return result
            transfer.prepare(old, target, retired, revision.pdf_hash, document.file_size)
            if not audit:
                # Preserve metadata timestamps and the entire frozen revision.
                ProjectDocument.objects.filter(pk=document.pk).update(document=target)
                DocumentAudit.objects.create(
                    revision=revision, actor=None, action=ACTION, detail=detail
                )
        # DB has committed before the old public path is retired. Audit permits
        # resume here, including when an exception/exit followed the commit.
        result["status"] = "retirement_pending"
        try:
            disposition = transfer.retire(
                old, target, retired, detail["sha256"], detail["byte_length"]
            )
            with transaction.atomic():
                revision = ElaboratoRevision.objects.select_for_update().get(pk=revision_id)
                DocumentAudit.objects.get_or_create(
                    revision=revision,
                    action=RETIRED_ACTION,
                    defaults={"actor": None, "detail": {**detail, "disposition": disposition}},
                )
            result.update(
                {
                    "status": "migrated",
                    "retirement": disposition,
                    "public_present": False,
                    "private_present": True,
                    "retired_present": disposition == "retired",
                }
            )
        except (OSError, TransferBlocked) as exc:
            result["reason"] = (
                str(exc) if isinstance(exc, TransferBlocked) else "retirement_io_error"
            )
        return result
    except (OSError, TransferBlocked) as exc:
        result["reason"] = str(exc) if isinstance(exc, TransferBlocked) else "storage_io_error"
        return result


def transfer_batch(*, apply=False, maintenance=False, revision_id=None, limit=200, after=None):
    query = ElaboratoRevision.objects.exclude(drive_document_id=None).order_by("pk")
    if revision_id:
        query = query.filter(pk=revision_id)
    if after:
        query = query.filter(pk__gt=after)
    ids = list(query.values_list("pk", flat=True)[: max(0, min(limit, 200))])
    return [transfer_revision(pk, apply=apply, maintenance=maintenance) for pk in ids]
