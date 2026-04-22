import json
from pathlib import Path

from django.core.management import call_command

from edilcloud.modules.projects.demo_master_blueprint_media import (
    collect_audio_jobs,
    collect_document_jobs,
    collect_drawing_jobs,
    collect_image_jobs,
    load_editorial_blueprint,
)


def test_collect_demo_blueprint_media_jobs_uses_attachment_root():
    blueprint = load_editorial_blueprint()

    document_jobs = collect_document_jobs(blueprint)
    drawing_jobs = collect_drawing_jobs(blueprint)
    image_jobs = collect_image_jobs(blueprint)
    audio_jobs = collect_audio_jobs(blueprint)

    assert any(job.document_ref == "checklist-valvole-bilanciamento.pdf" for job in document_jobs)
    assert any(job.document_ref == "punch-list-parti-comuni.pdf" for job in document_jobs)
    assert all(job.output_path.parent.name == "documents" for job in document_jobs)
    assert len(document_jobs) == 14

    document_job_map = {job.document_ref: job for job in document_jobs}
    assert len(document_job_map["rapportino-sopralluogo-vmc-corridoio-nord.pdf"].usages) == 2
    assert len(document_job_map["verbale-sopralluogo-bagno-campione-2b.pdf"].usages) == 2
    assert len(document_job_map["punch-list-parti-comuni.pdf"].usages) == 3
    assert any(usage.scope == "thread_comment" for usage in document_job_map["checklist-valvole-bilanciamento.pdf"].usages)
    assert all(any(usage.post_summary_it for usage in job.usages) for job in document_jobs)

    assert any(job.drawing_code == "st-204" and job.aspect_ratio == "16:9" for job in drawing_jobs)
    assert any(job.drawing_code == "fa-312" and job.aspect_ratio == "3:4" for job in drawing_jobs)
    assert all(job.output_path.parent.name == "drawings" for job in drawing_jobs)

    assert any(job.asset_stem == "mockup-facciata-sud-ovest" and job.aspect_ratio == "16:9" for job in image_jobs)
    assert any(
        job.asset_stem == "quote-massetti-1a-dettaglio-picchetto" and job.aspect_ratio == "3:4"
        for job in image_jobs
    )
    assert all(job.output_path.parent.name == "attachments" for job in image_jobs)

    assert any(
        job.audio_ref == "foundation-box-03-04-field-note" and job.voice_name == "Achird"
        for job in audio_jobs
    )
    assert any(job.audio_ref == "handover-task-overview-note" and job.voice_name == "Kore" for job in audio_jobs)
    multilingual_audio_job_map = {job.audio_ref: job for job in audio_jobs}
    assert multilingual_audio_job_map["foundation-scavo-fronte-nord-note"].language == "fr"
    assert multilingual_audio_job_map["foundation-scavo-fronte-nord-note"].speaker_code == "omar-elidrissi"
    assert multilingual_audio_job_map["structures-solai-passaggi-note"].language == "ro"
    assert multilingual_audio_job_map["structures-solai-passaggi-note"].speaker_code == "bogdan-muresan"
    assert multilingual_audio_job_map["interiors-bagno-alina-note"].language == "ro"
    assert multilingual_audio_job_map["interiors-bagno-alina-note"].speaker_code == "alina-popescu"
    assert all(job.output_path.parent.name == "attachments" for job in audio_jobs)


def test_generate_demo_master_blueprint_media_dry_run_writes_manifest(tmp_path):
    manifest_path = tmp_path / "generated-media-manifest.json"

    call_command(
        "generate_demo_master_blueprint_media",
        dry_run=True,
        manifest_path=str(manifest_path),
        limit_documents=2,
        limit_drawings=2,
        limit_images=2,
        limit_audio=2,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["stats"]["document_jobs"] == 2
    assert manifest["stats"]["drawing_jobs"] == 2
    assert manifest["stats"]["image_jobs"] == 2
    assert manifest["stats"]["audio_jobs"] == 2
    assert len(manifest["documents"]) == 2
    assert len(manifest["drawings"]) == 2
    assert len(manifest["images"]) == 2
    assert len(manifest["audio"]) == 2
    assert Path(manifest_path).exists()
