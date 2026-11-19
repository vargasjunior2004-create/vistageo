import io
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

import pytest

from app import migrar_fotografias
from app.migrar_fotografias import Photo, Storage, StorageTransientError


def test_storage_acepta_variables_de_entorno_y_exige_mismo_proyecto(monkeypatch):
    project = "abcdefghijklmnopqrst"
    monkeypatch.setattr("app.storage.database_url", lambda: (
        f"postgresql+psycopg://postgres.{project}:test@pool.example:5432/postgres"
        "?sslmode=verify-full&sslrootcert=%2Ftmp%2Fca.pem"
    ))
    monkeypatch.setenv("SUPABASE_URL", f"https://{project}.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    assert Storage().origin == f"https://{project}.supabase.co/storage/v1"
    monkeypatch.setenv("SUPABASE_URL", "https://zyxwvutsrqponmlkjihg.supabase.co")
    with pytest.raises(RuntimeError, match="mismo proyecto"):
        Storage()


@pytest.mark.parametrize(("url", "db_suffix", "key", "message"), [
    ("https://abcdefghijklmnopqrst.supabase.co/storage/v1", "?sslmode=verify-full&sslrootcert=ca", "sb_secret_test", "componentes adicionales"),
    ("https://abcdefghijklmnopqrst.supabase.co:secret", "?sslmode=verify-full&sslrootcert=ca", "sb_secret_test", "formato de SUPABASE_URL"),
    ("https://abcdefghijklmnopqrst.supabase.co", "?sslmode=require", "sb_secret_test", "TLS verificado"),
    ("https://abcdefghijklmnopqrst.supabase.co", "?sslmode=verify-full&sslrootcert=ca", "clave-privada", "SUPABASE_SECRET_KEY"),
])
def test_storage_diagnostico_no_expone_valores(monkeypatch, url, db_suffix, key, message):
    database = "postgresql+psycopg://postgres.abcdefghijklmnopqrst:contrasena-privada@pool.example/postgres" + db_suffix
    monkeypatch.setattr("app.storage.database_url", lambda: database)
    monkeypatch.setenv("SUPABASE_URL", url)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", key)
    with pytest.raises(RuntimeError, match=message) as error:
        Storage()
    assert url not in str(error.value)
    assert key not in str(error.value)
    assert "contrasena-privada" not in str(error.value)


def test_storage_distingue_objeto_ausente_de_error():
    class Opener:
        def __init__(self, code, body):
            self.code, self.body = code, body

        def open(self, request, timeout):
            raise HTTPError(request.full_url, self.code, "error", {}, io.BytesIO(self.body))

    storage = Storage.__new__(Storage)
    storage.origin = "https://example.invalid/storage/v1"
    storage.key = "secret-test"
    storage.opener = Opener(400, b'{"error":"not_found"}')
    assert storage.get("missing.webp") is None
    storage.opener = Opener(403, b'{"error":"unauthorized"}')
    with pytest.raises(RuntimeError, match="HTTP 403"):
        storage.get("missing.webp")
    storage.opener = Opener(400, b'{"error":"other"}')
    with pytest.raises(RuntimeError, match="HTTP 400"):
        storage.get("missing.webp")
    storage.opener = Opener(503, b'{}')
    with pytest.raises(StorageTransientError):
        storage.get("missing.webp")
    storage.opener = Opener(520, b'{}')
    with pytest.raises(StorageTransientError):
        storage.get("missing.webp")


def test_storage_elimina_solo_la_clave_exacta_con_api_json():
    class Opener:
        def open(self, request, timeout):
            assert request.method == "DELETE"
            assert request.full_url.endswith("/object/fachada")
            assert request.get_header("Content-type") == "application/json"
            assert json.loads(request.data) == {"prefixes": ["historicas/a %.webp"]}
            return io.BytesIO(b"[]")

    storage = Storage.__new__(Storage)
    storage.origin = "https://example.invalid/storage/v1"
    storage.key = "secret-test"
    storage.opener = Opener()
    storage.delete("historicas/a %.webp")


def test_reintenta_fallo_transitorio_sin_ocultar_errores_permanentes(monkeypatch):
    calls = []
    photo = Photo("k", 1, 1, "a" * 64, "b" * 64, Path("imagen.webp"))
    storage = Storage.__new__(Storage)

    def flaky(photo, storage):
        calls.append(None)
        if len(calls) < 3:
            raise StorageTransientError("red")
        return "creada"

    monkeypatch.setattr(migrar_fotografias, "import_photo", flaky)
    monkeypatch.setattr(migrar_fotografias.time, "sleep", lambda delay: None)
    assert migrar_fotografias.import_with_retries(photo, storage) == "creada"
    assert len(calls) == 3

    def permanent(photo, storage):
        raise ValueError("conflicto")

    monkeypatch.setattr(migrar_fotografias, "import_photo", permanent)
    with pytest.raises(ValueError, match="conflicto"):
        migrar_fotografias.import_with_retries(photo, storage)


def test_storage_envia_webp_y_recupera_mismos_bytes():
    class Handler(BaseHTTPRequestHandler):
        stored = None

        def log_message(self, format, *args):
            pass

        def do_GET(self):
            if self.stored is None:
                body = b'{"error":"not_found"}'
                self.send_response(400)
            else:
                body = self.stored
                self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            assert self.headers["x-upsert"] == "false"
            assert self.headers["Content-Type"] == "image/webp"
            type(self).stored = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        storage = Storage.__new__(Storage)
        storage.origin = f"http://127.0.0.1:{server.server_port}/storage/v1"
        storage.key = "secret-test"
        storage.opener = build_opener(ProxyHandler({}))
        assert storage.get("key.webp") is None
        storage.put("key.webp", b"contenido")
        assert storage.get("key.webp") == b"contenido"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
