import http.client
import ipaddress
import re
import socket
import ssl
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, unquote, urljoin, urlsplit


SHORT_HOSTS = {"maps.app.goo.gl", "goo.gl"}
MAP_HOSTS = {"google.com", "www.google.com", "maps.google.com", "www.openstreetmap.org", "openstreetmap.org"}
COORDINATES = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?),\s*([+-]?\d+(?:\.\d+)?)\s*$")
PLACE_COORDINATES = re.compile(r"!3d([+-]?\d+(?:\.\d+)?)!4d([+-]?\d+(?:\.\d+)?)(?=!|/|$)")


def validated_url(url: str):
    if len(url) > 4096 or any(char.isspace() or ord(char) < 32 for char in url):
        raise ValueError("Enlace GPS inválido")
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname not in SHORT_HOSTS | MAP_HOSTS
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443)):
            raise ValueError("Dominio o protocolo de mapa no compatible")
    except ValueError as exc:
        raise ValueError("Enlace GPS inválido o no compatible") from exc
    if parts.hostname == "goo.gl" and not parts.path.startswith("/maps/"):
        raise ValueError("Enlace corto no compatible")
    if parts.hostname in {"google.com", "www.google.com"} and not (parts.path == "/maps" or parts.path.startswith("/maps/")):
        raise ValueError("El enlace no corresponde a Google Maps")
    if parts.hostname == "maps.google.com" and parts.path not in ("", "/") and not (parts.path == "/maps" or parts.path.startswith("/maps/")):
        raise ValueError("El enlace no corresponde a Google Maps")
    if parts.hostname in {"openstreetmap.org", "www.openstreetmap.org"} and parts.path not in ("", "/"):
        raise ValueError("Enlace de OpenStreetMap no compatible")
    return parts


def parse_map_url(url: str) -> tuple[Decimal, Decimal]:
    parts = validated_url(url)
    if parts.hostname not in MAP_HOSTS:
        raise ValueError("El enlace corto necesita resolverse")
    if parts.hostname not in {"openstreetmap.org", "www.openstreetmap.org"}:
        path = parts.path
        if path not in ("", "/", "/maps", "/maps/", "/maps/search") and not (
            path.startswith("/maps/search/") or path.startswith("/maps/place/")
        ):
            raise ValueError("El enlace no representa una ubicación puntual")
    candidates = []
    params = parse_qs(parts.query, keep_blank_values=True)
    if parts.hostname in {"openstreetmap.org", "www.openstreetmap.org"}:
        latitudes, longitudes = params.get("mlat", []), params.get("mlon", [])
        if len(latitudes) != 1 or len(longitudes) != 1:
            raise ValueError("El enlace no contiene un marcador puntual")
        match = COORDINATES.fullmatch(f"{latitudes[0]},{longitudes[0]}")
        if match:
            candidates.append(match.groups())
    path = unquote(parts.path)
    if path in ("", "/", "/maps", "/maps/", "/maps/search", "/maps/search/"):
        for key in ("q", "query"):
            for value in params.get(key, []):
                match = COORDINATES.fullmatch(value)
                if match:
                    candidates.append(match.groups())
    if path.startswith("/maps/search/"):
        value = path.removeprefix("/maps/search/").rstrip("/")
        match = COORDINATES.fullmatch(value)
        if match:
            candidates.append(match.groups())
    if path.startswith("/maps/place/"):
        candidates.extend(PLACE_COORDINATES.findall(path))
    if not candidates:
        raise ValueError("El enlace no contiene una ubicación puntual reconocible")
    try:
        points = {(Decimal(lat), Decimal(lon)) for lat, lon in candidates}
    except InvalidOperation as exc:
        raise ValueError("Coordenadas inválidas") from exc
    if len(points) != 1:
        raise ValueError("El enlace contiene ubicaciones contradictorias")
    latitude, longitude = points.pop()
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Coordenadas fuera de rango")
    return latitude, longitude


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str):
        super().__init__(host, timeout=5, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except (OSError, ssl.SSLError):
            raw.close()
            raise


def redirect_location(url: str) -> str:
    parts = validated_url(url)
    host = parts.hostname
    if host not in SHORT_HOSTS:
        raise ValueError("El destino no es un enlace corto compatible")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = {item[4][0] for item in addresses}
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ValueError("El enlace apunta a una dirección no permitida")
        connection = PinnedHTTPSConnection(host, sorted(ips)[0])
        try:
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            connection.request("GET", path, headers={"Accept": "*/*", "Connection": "close"})
            response = connection.getresponse()
            location = response.getheader("Location")
            if response.status not in (301, 302, 303, 307, 308) or not location:
                raise ValueError("No se pudo resolver el enlace corto")
            return urljoin(url, location)
        finally:
            connection.close()
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise ValueError("No se pudo resolver el enlace corto; inténtalo nuevamente") from exc


def resolve_map_url(url: str) -> tuple[Decimal, Decimal]:
    current = url
    visited = set()
    for _ in range(6):
        parts = validated_url(current)
        if parts.hostname in MAP_HOSTS:
            return parse_map_url(current)
        if current in visited:
            raise ValueError("El enlace contiene redirecciones repetidas")
        visited.add(current)
        current = redirect_location(current)
    raise ValueError("El enlace contiene demasiadas redirecciones")
