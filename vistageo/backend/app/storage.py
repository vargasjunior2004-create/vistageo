import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from sqlalchemy.engine import make_url

from app.database import database_url

BUCKET = "fachada"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class StorageTransientError(RuntimeError):
    pass


class Storage:
    def __init__(self):
        db = make_url(database_url())
        url = urlsplit(os.environ.get("SUPABASE_URL", ""))
        self.key = os.environ.get("SUPABASE_SECRET_KEY")
        project = (url.hostname or "").removesuffix(".supabase.co")
        if (url.scheme != "https" or not url.hostname or url.hostname != f"{project}.supabase.co"
                or not re.fullmatch(r"[a-z0-9]{20}", project) or url.username or url.password or url.port
                or url.path not in ("", "/") or url.query or url.fragment
                or not (db.username == f"postgres.{project}" or db.host == f"db.{project}.supabase.co")
                or db.query.get("sslmode") != "verify-full" or not db.query.get("sslrootcert")
                or not self.key or not self.key.startswith("sb_secret_")):
            raise RuntimeError("Storage y PostgreSQL deben usar el mismo proyecto y TLS verificado")
        self.origin = f"https://{url.hostname}/storage/v1"
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method: str, path: str, data: bytes | None = None) -> bytes | None:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}"}
        if data is not None:
            if method == "DELETE":
                headers["Content-Type"] = "application/json"
            else:
                headers.update({"Content-Type": "image/webp", "x-upsert": "false"})
        request = Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=60) as response:
                result = response.read(10 * 1024 * 1024 + 1)
                if len(result) > 10 * 1024 * 1024:
                    raise RuntimeError("Respuesta de Storage demasiado grande")
                return result
        except HTTPError as exc:
            if method == "GET" and exc.code in (400, 404):
                try:
                    error = json.loads(exc.read())
                except (ValueError, UnicodeDecodeError):
                    error = {}
                if error.get("error") == "not_found":
                    return None
            if exc.code in (408, 429) or 500 <= exc.code < 600:
                raise StorageTransientError(f"Storage temporalmente no disponible (HTTP {exc.code})") from None
            raise RuntimeError(f"Storage rechazó la operación ({method}, HTTP {exc.code})") from None
        except URLError as exc:
            raise StorageTransientError(f"Error de conexión o TLS en Storage: {type(exc.reason).__name__}") from None
        except (TimeoutError, ConnectionError) as exc:
            raise StorageTransientError(f"Conexión a Storage interrumpida: {type(exc).__name__}") from None

    def get(self, key: str) -> bytes | None:
        return self.request("GET", f"/object/authenticated/{BUCKET}/{quote(key, safe='/')}")

    def put(self, key: str, data: bytes) -> None:
        self.request("POST", f"/object/{BUCKET}/{quote(key, safe='/')}", data)

    def delete(self, key: str) -> None:
        self.request("DELETE", f"/object/{BUCKET}", json.dumps({"prefixes": [key]}).encode())

    def check_bucket(self, max_size: int) -> None:
        result = self.request("GET", f"/bucket/{BUCKET}")
        if result is None:
            raise RuntimeError("No existe el bucket configurado")
        bucket = json.loads(result)
        if bucket.get("id") != BUCKET or bucket.get("public") is not False:
            raise RuntimeError("El bucket no existe o no es privado")
        if bucket.get("file_size_limit") is not None and bucket["file_size_limit"] < max_size:
            raise RuntimeError("El límite de archivo del bucket es insuficiente")
