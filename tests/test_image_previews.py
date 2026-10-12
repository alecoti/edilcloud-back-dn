from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image
import pytest
from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from edilcloud.modules.files.image_storage import OptimizedImageStorage, image_variant_payload


def image_bytes(mode="RGB", size=(2400, 1600), format="PNG", **save_args):
    image = Image.effect_noise(size, 60).convert(mode)
    if mode == "RGBA":
        image.putalpha(100)
    stream = BytesIO()
    image.save(stream, format=format, **save_args)
    return stream.getvalue()


def test_upload_creates_smaller_previews_and_retains_exact_original(tmp_path):
    storage = OptimizedImageStorage(location=tmp_path, base_url="/media/")
    original = image_bytes()
    name = storage.save("projects/20/photos/photo.png", ContentFile(original))
    assert (tmp_path / name).read_bytes() == original
    metadata = storage.image_metadata(name)
    assert [max(v["width"], v["height"]) for v in metadata["variants"]] == [320, 960, 1920]
    for variant in metadata["variants"]:
        with Image.open(tmp_path / variant["name"]) as image:
            assert image.format == "WEBP"
            assert image.size == (variant["width"], variant["height"])
        assert variant["size"] < len(original)


def test_preview_transparency_orientation_and_no_upscale(tmp_path):
    storage = OptimizedImageStorage(location=tmp_path)
    name = storage.save("transparent.png", ContentFile(image_bytes("RGBA", (128, 64))))
    variants = storage.image_metadata(name)["variants"]
    assert len(variants) == 1
    with Image.open(tmp_path / variants[0]["name"]) as preview:
        assert preview.size == (128, 64)
        assert preview.getpixel((0, 0))[3] == 100
    exif = Image.Exif()
    exif[274] = 6
    name = storage.save("vertical.jpg", ContentFile(image_bytes(size=(1600, 900), format="JPEG", quality=100, exif=exif)))
    metadata = storage.image_metadata(name)
    assert all(v["height"] > v["width"] for v in metadata["variants"])


def test_backfill_is_idempotent_and_read_paths_do_not_decode(tmp_path, monkeypatch):
    storage = OptimizedImageStorage(location=tmp_path)
    original = image_bytes(size=(1200, 800))
    path = tmp_path / "legacy.png"
    path.write_bytes(original)
    first = storage.prepare_image_previews("legacy.png")
    monkeypatch.setattr(Image, "open", lambda *a, **kw: pytest.fail("Image decoded during cached read"))
    assert storage.prepare_image_previews("legacy.png") == first
    assert storage.image_metadata("legacy.png") == first
    assert path.read_bytes() == original
    field = type("Field", (), {"storage": storage, "name": "legacy.png"})()
    assert image_variant_payload(field)["image_variants"][0]["url"].endswith(".webp")


def test_animated_images_and_non_images_keep_original(tmp_path):
    storage = OptimizedImageStorage(location=tmp_path)
    stream = BytesIO()
    Image.new("RGBA", (16, 16), "red").save(stream, "PNG", save_all=True,
        append_images=[Image.new("RGBA", (16, 16), "blue")], duration=100, loop=0)
    content = stream.getvalue()
    name = storage.save("animation.png", ContentFile(content))
    assert storage.image_metadata(name) == {}
    assert (tmp_path / name).read_bytes() == content
    name = storage.save("drawing.pdf", ContentFile(b"drawing-original"))
    assert storage.image_metadata(name) == {}


def test_preview_failure_does_not_reject_upload(tmp_path, monkeypatch):
    storage = OptimizedImageStorage(location=tmp_path)
    monkeypatch.setattr(storage, "prepare_image_previews", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    original = image_bytes(size=(64, 64))
    name = storage.save("photo.png", ContentFile(original))
    assert (tmp_path / name).read_bytes() == original


def test_duplicate_demo_files_share_previews_without_decoding_again(tmp_path, monkeypatch):
    storage = OptimizedImageStorage(location=tmp_path)
    original = image_bytes(size=(1200, 800))
    first = storage.save("projects/20/demo.png", ContentFile(original))
    monkeypatch.setattr(Image, "open", lambda *a, **kw: pytest.fail("Duplicate image decoded again"))
    second = storage.save("projects/99/demo-copy.png", ContentFile(original))
    assert storage.image_metadata(first)["variants"] == storage.image_metadata(second)["variants"]
    assert storage.image_metadata(first)["source"] != storage.image_metadata(second)["source"]
    assert (tmp_path / first).read_bytes() == (tmp_path / second).read_bytes() == original


@pytest.mark.parametrize("content", ['[]', '{"source":"photo.png"}', '{"variants":[{"width":0}]}'])
def test_corrupt_preview_metadata_falls_back_without_breaking_api(tmp_path, content):
    storage = OptimizedImageStorage(location=tmp_path)
    manifest = tmp_path / storage._manifest_name("photo.png")
    manifest.parent.mkdir(parents=True)
    manifest.write_text(content)
    assert storage.image_metadata("photo.png") == {}


def test_duplicate_upload_optimization_reuses_bytes_and_keeps_filename_and_settings(monkeypatch):
    from edilcloud.modules.files import media_optimizer
    content = image_bytes(size=(1200, 800), format="JPEG", quality=100)
    original = media_optimizer._optimize_image
    calls = []
    def optimize(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(media_optimizer, "_optimize_image", optimize)
    outputs = []
    for filename in ["first.jpg", "second.jpg"]:
        outputs.append(media_optimizer.optimize_media_for_storage(SimpleUploadedFile(filename, content, content_type="image/jpeg")))
    assert len(calls) == 1
    assert outputs[1].name == "second.jpg"
    assert outputs[0].read() == outputs[1].read()
    for output in outputs:
        output.close()
    with override_settings(MEDIA_IMAGE_JPEG_QUALITY=60):
        changed = media_optimizer.optimize_media_for_storage(SimpleUploadedFile("third.jpg", content, content_type="image/jpeg"))
        assert len(calls) == 2
        changed.close()
