import io
from decimal import Decimal
from zipfile import ZipFile

from app.migrar_ubicaciones import build_plan, coordinates, first_map_url


def docx(body: str, relationships: str = "") -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="urn:word" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<w:body>{body}</w:body></w:document>",
        )
        archive.writestr("word/_rels/document.xml.rels", f"<Relationships>{relationships}</Relationships>")
    return output.getvalue()


def test_primera_url_respeta_orden_de_documento_y_descarta_enlaces_ajenos():
    data = docx(
        '<w:p><w:hyperlink r:id="r1"><w:t>mapa</w:t></w:hyperlink>'
        '<w:t> https://maps.google.com/?q=-16.0,-68.0</w:t></w:p>',
        '<Relationship Id="r1" TargetMode="External" Target="https://maps.google.com/first"/>',
    )
    assert first_map_url(data) == "https://maps.google.com/first"
    split = docx("<w:p><w:t>https://maps.</w:t><w:t>google.com/?q=-16.5,-68.1</w:t></w:p>")
    assert first_map_url(split) == "https://maps.google.com/?q=-16.5,-68.1"
    unrelated = docx("<w:p><w:t>https://example.com/</w:t></w:p>")
    assert first_map_url(unrelated) is None


def test_coordenadas_solo_si_aparecen_y_son_validas():
    assert coordinates("https://www.google.com/maps/@-16.5,-68.1,17z") == (Decimal("-16.5"), Decimal("-68.1"))
    assert coordinates("https://maps.google.com/?q=-16.5%2C-68.1") == (Decimal("-16.5"), Decimal("-68.1"))
    assert coordinates("https://maps.google.com/?q=99.0,12.0") == (None, None)
    assert coordinates("https://maps.app.goo.gl/example") == (None, None)


def test_plan_toma_primer_documento_con_enlace_de_cada_carpeta(monkeypatch, tmp_path):
    first = docx("<w:p><w:t>https://maps.google.com/first</w:t></w:p>")
    second = docx("<w:p><w:t>https://maps.google.com/second</w:t></w:p>")

    def fake_inventory(_path, consume):
        consume("raiz/123/primero.docx", first)
        consume("raiz/123/segundo.docx", second)
        consume("raiz/456/vacio.docx", b"")
        return [{"ruta_original": "x"}], "a" * 64

    monkeypatch.setattr("app.migrar_ubicaciones.build_inventory", fake_inventory)
    plan = build_plan(tmp_path / "source.rar")
    assert plan.links == {"123": ("raiz/123/primero.docx", "https://maps.google.com/first")}
    assert plan.invalid_documents == 1
