import csv
import io
from zipfile import ZipFile

import pytest
from PIL import Image

from app import optimizar_fotografias
from app.optimizar_fotografias import process, sha256_file


def image_bytes(size, orientation=None):
    buffer = io.BytesIO()
    image = Image.new("RGB", size, "red")
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def create_archive(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    archive_path = source / "original.zip"
    large = image_bytes((2400, 800), 6)
    small = image_bytes((40, 30))
    with ZipFile(archive_path, "w") as archive:
        for directory in ("raiz", "raiz/123-A", "raiz/123-A.1"):
            archive.writestr(directory + "/", b"")
        for name, data in {
            "raiz/123-A/large.jpg": large,
            "raiz/123-A/duplicate.jpg": small,
            "raiz/123-A.1/duplicate.jpg": small,
            "raiz/123-A.1/empty.jpg": b"",
            "raiz/123-A.1/broken.jpg": b"not an image",
        }.items():
            archive.writestr(name, data)
    return archive_path


def read_report(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return {row["ruta_original"]: row for row in csv.DictReader(stream)}


def test_optimizacion_integridad_reanudacion_y_conflicto(tmp_path):
    archive = create_archive(tmp_path)
    before = sha256_file(archive)
    output = tmp_path / "output"
    report, _, summary = process(archive, output)
    rows = read_report(report)
    assert (summary["imagenes_totales"], summary["procesadas"], summary["fallidas"]) == (5, 3, 2)
    large = rows["raiz/123-A/large.jpg"]
    assert large["kardex"] == "123-A"
    assert large["dimensiones_originales"] == "2400x800"
    assert large["dimensiones_finales"] == "533x1600"
    with Image.open(output / large["ruta_optimizada"]) as image:
        image.load()
        assert image.format == "WEBP" and image.size == (533, 1600)
        assert not image.getexif()
    small = rows["raiz/123-A/duplicate.jpg"]
    assert small["dimensiones_finales"] == "40x30"
    assert rows["raiz/123-A.1/duplicate.jpg"]["duplicado_de"] == "raiz/123-A/duplicate.jpg"
    assert rows["raiz/123-A.1/empty.jpg"]["estado"] == "FALLIDA"
    assert rows["raiz/123-A.1/broken.jpg"]["error"]
    second, _, repeated = process(archive, output)
    assert second != report
    assert (repeated["procesadas"], repeated["omitidas_reanudacion"], repeated["fallidas"]) == (0, 3, 2)
    target = output / large["ruta_optimizada"]
    target.write_bytes(b"modificado")
    third, _, changed = process(archive, output)
    assert changed["fallidas"] == 3
    assert "huella" in read_report(third)["raiz/123-A/large.jpg"]["error"]
    assert target.read_bytes() == b"modificado"
    assert sha256_file(archive) == before


def test_rechaza_salida_en_originales_o_directorio_ajeno(tmp_path):
    archive = create_archive(tmp_path)
    with pytest.raises(ValueError, match="fuera"):
        process(archive, archive.parent / "salida")
    other = tmp_path / "existing"
    other.mkdir()
    (other / "archivo.txt").write_text("intacto")
    with pytest.raises(ValueError, match="ajenos"):
        process(archive, other)
    assert (other / "archivo.txt").read_text() == "intacto"


def test_reanudacion_tras_interrupcion(tmp_path, monkeypatch):
    archive = create_archive(tmp_path)
    output = tmp_path / "output"
    original_build = optimizar_fotografias.build_inventory

    def interrupt(path, on_image):
        def consume(name, data):
            on_image(name, data)
            raise RuntimeError("interrupción simulada")
        return original_build(path, on_image=consume)

    monkeypatch.setattr(optimizar_fotografias, "build_inventory", interrupt)
    with pytest.raises(RuntimeError, match="interrupción simulada"):
        process(archive, output)
    monkeypatch.setattr(optimizar_fotografias, "build_inventory", original_build)
    _, _, summary = process(archive, output)
    assert (summary["procesadas"], summary["omitidas_reanudacion"], summary["fallidas"]) == (2, 1, 2)
