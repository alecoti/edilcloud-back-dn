"""Seed all six catalog types for real UI lifecycle checks, without external AI.

Only the preparation provider is synthetic. HTTP APIs, editors, signatures,
preview workers, renderer, publication and Drive paths remain real app code.
"""
from datetime import date
import io
import json
import os
from pathlib import Path
import re
import uuid


def main():
    if os.environ.get('DJANGO_SETTINGS_MODULE') != 'tests.elaborati_runtime_settings':
        raise SystemExit('Only the owned loopback integration settings are allowed.')
    database = os.environ.get('ELABORATI_RUNTIME_DATABASE', '')
    if not re.fullmatch(r'edilcloud_elaborati_qa_[0-9a-f]{12}', database):
        raise SystemExit('An explicitly owned QA database is required.')
    import django
    django.setup()
    from django.conf import settings
    from django.core.files.base import ContentFile
    from django.db import transaction
    from PIL import Image, ImageDraw
    import pytest
    from edilcloud.modules.elaborati import services
    from edilcloud.modules.elaborati.content import Composition, QualityResult, ReasoningResult
    from edilcloud.modules.elaborati.jobs import process_job
    from edilcloud.modules.elaborati.models import DocumentAIUsage, DocumentJob
    from edilcloud.modules.elaborati.registry import TYPES
    from edilcloud.modules.elaborati.schemas import CreateRequest
    from edilcloud.modules.projects.models import ProjectPhoto, ProjectPost
    from edilcloud.modules.workspaces.models import Profile

    runtime = Path(settings.PRIVATE_STORAGE_ROOT).parent
    context_path = runtime / 'context.json'
    context = json.loads(context_path.read_text(encoding='utf-8'))
    if context['database'] != database or context.get('synthetic_only') is not True:
        raise SystemExit('Database ownership is not established.')
    if 'six_types' in context.get('qa_cases', {}):
        raise SystemExit('The batch already exists. Preserve its state and evidence.')
    evidence = runtime.parents[2] / 'docs/elaborati/20261025/evidence'
    # runtime.parents[2] is the workspace root, outside the isolated repositories.
    receipt_path = evidence / 'six-type-seed.json'
    prior_attempt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    if prior_attempt and prior_attempt.get('state') != 'rolled_back':
        raise SystemExit('Inspect the previous seed attempt before repeating mutations.')
    receipt = {'synthetic_only': True, 'database': database, 'state': 'preparing', 'cases': {}}
    if prior_attempt:
        receipt['prior_attempt'] = prior_attempt
    receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')
    owner = Profile.objects.get(pk=context['profile_id'], user_id=context['user_id'])
    project_id = context['project_id']
    before_usage = DocumentAIUsage.objects.count()
    before_jobs = DocumentJob.objects.count()
    descriptions = {
        'daily_report': ['Giornata sintetica di prova.', 'Verifica delle finiture proposta, non conclusa.',
                         'Criticità non valutate nel campione.', 'Meteo non disponibile nel campione.',
                         'Orari e presenze ancora da verificare.'],
        'inspection': ['Sopralluogo sintetico nel bagno B203.', 'Partecipanti da confermare.',
                       'Rilievo sintetico sulle finiture, non sopralluogo reale.',
                       'Indicazione proposta: controllare le finiture.', 'Esito della verifica non disponibile.'],
        'coordination': ['Riunione sintetica di coordinamento.', 'Partecipanti da confermare.',
                         'Argomento proposto: verifica delle finiture.', 'Nessuna decisione reale registrata.',
                         'Responsabile e scadenza da confermare.'],
        'periodic_report': ['Riepilogo sintetico del periodo.', 'Avanzamenti e quantità non verificati.',
                            'Criticità ancora da valutare.', 'Nessuna decisione reale registrata.',
                            'Immagine di prova disponibile fra le fonti.', 'Mancano esiti e misure confermati.'],
        'photo_report': ['Immagine sintetica: nessun luogo reale ripreso.',
                         'Tavola grafica preparata esclusivamente per la prova.',
                         'Il campione verifica impaginazione e riferimenti.',
                         'Luogo e rilievi reali non disponibili.'],
        'issue_report': ['Criticità sintetica da verificare.',
                         'Proposta registrata nel campione; nessuna chiusura confermata.',
                         'La comunicazione è una fonte sintetica di prova.',
                         'Esito reale non disponibile.', 'Responsabile e risoluzione da confermare.'],
    }
    provider_calls = []
    active = {}

    def provider(*, job, stage, schema, data, **kwargs):
        provider_calls.append({'case': active['case'], 'stage': stage})
        if schema is ReasoningResult:
            return ReasoningResult(facts=[], duplicates=[], contradictions=[],
                                   missing_data=['Campione sintetico: dati operativi non verificati.'])
        if schema is QualityResult:
            return QualityResult(issues=[], missing_data=['Verifica professionale non eseguita: fixture QA.'])
        if schema is not Composition:
            raise AssertionError(f'Unexpected preparation stage: {stage}')
        template = data['template']
        text = descriptions[active['type']]
        assert len(text) == len(template['sections'])
        photos = []
        if active['type'] == 'photo_report':
            photos = [{'source_id': active['photo_source'], 'section_key': 'section_2',
                'title': 'Immagine sintetica QA', 'layout': 'full',
                'caption': {'text': active['case'] + '-PHOTO — immagine generata per il test, non foto di cantiere.',
                            'source_ids': [active['photo_source']], 'nature': 'unverified'}}]
        return Composition(title='QA6 ' + active['label'], subtitle='Campione sintetico, non documento professionale',
            sections=[{'key': section['key'], 'paragraphs': [{
                'text': f"{active['case']}-S{index+1} — {text[index]}",
                'source_ids': [active['post_source']], 'nature': 'unverified'}]}
                for index, section in enumerate(template['sections'])], photographs=photos)

    with transaction.atomic(), pytest.MonkeyPatch.context() as patch:
        patch.setattr('edilcloud.modules.elaborati.engine.structured_response', provider)
        # Media reading would be a distinct billable provider call. This fixture
        # deliberately has no visual interpretation; only real image embedding
        # and the supplied, explicitly synthetic caption are being qualified.
        patch.setattr('edilcloud.modules.elaborati.media_sources.enrich_media',
                      lambda *, job, bundle: bundle)
        post = ProjectPost.objects.create(project_id=project_id, author=owner,
            text='QA6 DATI SINTETICI. Proposta di controllo finiture del bagno B203. '
                 'Nessun esito, presenza, quantità, decisione o criticità reale attestati.')
        image = Image.new('RGB', (1000, 560), '#e4edf5')
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((45, 45, 955, 515), outline='#334455', width=6)
        drawing.text((90, 100), 'QA6 - IMMAGINE SINTETICA DI PROVA', fill='#152638', font_size=34)
        drawing.text((90, 185), 'NON E UNA FOTO DI CANTIERE', fill='#152638', font_size=30)
        for x in range(100, 900, 100):
            drawing.rectangle((x, 300, x+55, 435), fill=(x//5, 110, 160))
        content = io.BytesIO()
        image.save(content, format='PNG')
        photo = ProjectPhoto.objects.create(project_id=project_id, uploaded_by=owner,
            title='QA6 immagine sintetica, non fotografia reale',
            photo=ContentFile(content.getvalue(), name='qa6-synthetic.png'))
        for client, short in [('web', 'W'), ('flutter', 'F')]:
            for backend, suffix in [('django', 'D'), ('rust', 'R')]:
                for kind in TYPES:
                    case = f'{short}{suffix}-{kind}'
                    active.update(case=case, type=kind, label=f'{short}{suffix} {kind}',
                                  post_source=f'post:{post.pk}', photo_source=f'photo:{photo.pk}')
                    revision = services.create_elaborato(profile=owner, payload=CreateRequest(
                        idempotency_key=uuid.uuid5(uuid.NAMESPACE_URL, f'edilcloud-qa-six-types/{case}'),
                        project_id=project_id, document_type=kind,
                        period_start=date(2026, 10, 26), period_end=date(2026, 10, 26),
                        language='it', context='Campione sintetico di test: nessun fatto reale attestato.'))
                    job = revision.jobs.get()
                    assert process_job(job.pk)
                    revision.refresh_from_db()
                    job.refresh_from_db()
                    assert job.state == 'completed', job.error_message
                    assert revision.editor_doc.get('type') == 'doc' and revision.state == 'draft'
                    assert revision.template_snapshot['key'] == kind
                    text = json.dumps(revision.editor_doc, ensure_ascii=False)
                    assert all(f'{case}-S{i+1}' in text for i in range(len(TYPES[kind][1])))
                    if kind == 'photo_report':
                        assert f'{case}-PHOTO' in text
                    key = f'{client}_{backend}_{kind}'
                    receipt['cases'][key] = {'revision':str(revision.pk), 'case':case,
                        'type':kind, 'client':client, 'backend':backend, 'version':revision.version,
                        'sections':revision.template_snapshot['sections'], 'job':str(job.pk),
                        'title':revision.elaborato.title}
                    print(json.dumps({'prepared':key,'revision':str(revision.pk)}), flush=True)
        assert DocumentAIUsage.objects.count() == before_usage == 0
        assert DocumentJob.objects.count() == before_jobs + 24
        assert not DocumentJob.objects.filter(state__in=['queued','running']).exists()
    revisions = {key: item['revision'] for key,item in receipt['cases'].items()}
    context.setdefault('qa_cases', {})['six_types'] = revisions
    context['six_type_cases'] = receipt['cases']
    context['six_type_post_id'] = post.pk
    context['six_type_photo_id'] = photo.pk
    context_path.write_text(json.dumps(context, indent=2)+'\n', encoding='utf-8')
    receipt.update(state='prepared', provider_calls=provider_calls, external_ai_requests=0,
                   ai_usage_rows=0, post_id=post.pk, photo_id=photo.pk)
    receipt_path.write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'prepared_cases':len(revisions),'simulated_stages':len(provider_calls),
                      'external_ai_requests':0}), flush=True)


if __name__ == '__main__':
    main()
