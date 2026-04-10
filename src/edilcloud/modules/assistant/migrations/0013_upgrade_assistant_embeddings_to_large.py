from django.db import migrations
import pgvector.django.vector


REINDEX_MESSAGE = "Reindex required after assistant embedding upgrade to text-embedding-3-large (3072d)."


def reset_pgvector_chunks_for_large_embeddings(apps, schema_editor):
    ChunkMap = apps.get_model("assistant", "ProjectAssistantChunkMap")
    ChunkSource = apps.get_model("assistant", "ProjectAssistantChunkSource")
    State = apps.get_model("assistant", "ProjectAssistantState")

    ChunkMap.objects.all().delete()
    ChunkSource.objects.all().update(
        chunk_count=0,
        is_indexed=False,
        last_indexed_at=None,
        last_error=REINDEX_MESSAGE,
    )
    State.objects.all().update(
        chunk_count=0,
        last_indexed_version=0,
        last_indexed_at=None,
        is_dirty=True,
        background_sync_scheduled=True,
        last_sync_error=REINDEX_MESSAGE,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0012_assistant_chunk_pgvector_store"),
    ]

    operations = [
        migrations.RunPython(
            reset_pgvector_chunks_for_large_embeddings,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="projectassistantchunkmap",
            name="embedding",
            field=pgvector.django.vector.VectorField(blank=True, dimensions=3072, null=True),
        ),
    ]
