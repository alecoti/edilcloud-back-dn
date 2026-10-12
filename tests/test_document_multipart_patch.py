from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.test.client import encode_multipart

from edilcloud.modules.projects.api import parse_project_document_update_payload


def test_multipart_patch_parses_file_and_title_instead_of_silent_noop():
    request = RequestFactory().patch(
        "/api/v1/documents/42",
        data=encode_multipart("BozzaBoundary", {
            "title": "Revisione sintetica",
            "document": SimpleUploadedFile(
                "bozza.md", b"# Bozza\nRevisione due.", content_type="text/markdown"
            ),
        }),
        content_type="multipart/form-data; boundary=BozzaBoundary",
    )
    parsed = parse_project_document_update_payload(request)
    assert parsed["title"] == "Revisione sintetica"
    assert parsed["uploaded_file"].name == "bozza.md"
    assert parsed["uploaded_file"].read() == b"# Bozza\nRevisione due."
