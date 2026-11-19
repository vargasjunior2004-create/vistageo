import io
import tarfile
import zlib

import pytest

from app.inventario_historico import main, read_archive


def archive_with_files(tmp_path, symlink=False):
    path = tmp_path / "source.tar"
    contents = {"original/001/a.docx": b"documento", "original/001/foto.jpg": b""}
    with tarfile.open(path, "w") as archive:
        for name, data in contents.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
        if symlink:
            entry = tarfile.TarInfo("original/001/enlace")
            entry.type = tarfile.SYMTYPE
            entry.linkname = "a.docx"
            archive.addfile(entry)
    expected = {name: (len(data), f"{zlib.crc32(data):08X}") for name, data in contents.items()}
    return path, expected


def test_lectura_inventaria_sin_extraer_y_conserva_ruta(tmp_path):
    path, expected = archive_with_files(tmp_path)
    entries = read_archive(path, expected)
    assert {entry["ruta_original"] for entry in entries} == set(expected)
    assert {entry["tipo"] for entry in entries} == {"documento", "imagen"}
    assert all(entry["estado_revision"] == "PENDIENTE" and entry["kardex"] is None for entry in entries)
    assert all(len(entry["sha256"]) == 64 for entry in entries)
    assert not (tmp_path / "original").exists()


def test_lectura_rechaza_crc_y_entradas_inesperadas(tmp_path):
    path, expected = archive_with_files(tmp_path)
    name = next(iter(expected))
    expected[name] = (expected[name][0], "00000000")
    with pytest.raises(ValueError, match="CRC"):
        read_archive(path, expected)
    path, expected = archive_with_files(tmp_path, symlink=True)
    with pytest.raises(ValueError, match="archivo regular"):
        read_archive(path, expected)


def test_aplicacion_rechaza_fuente_distinta_de_la_simulacion(tmp_path, monkeypatch):
    path, _ = archive_with_files(tmp_path)
    monkeypatch.setattr("app.inventario_historico.build_inventory", lambda _: ([{}], "a" * 64))
    monkeypatch.setattr("sys.argv", [
        "inventario_historico", str(path), "--aplicar",
        "--sha256-esperado", "b" * 64, "--cantidad-esperada", "1",
    ])
    with pytest.raises(SystemExit, match="no coinciden"):
        main()
