from decimal import Decimal

import pytest

from app.enlaces_gps import parse_map_url, resolve_map_url


@pytest.mark.parametrize("url", [
    "https://www.google.com/maps/search/?api=1&query=-16.5%2C-68.1",
    "https://maps.google.com/maps?q=-16.5,-68.1",
    "https://www.google.com/maps/place/casa/data=!3d-16.5!4d-68.1",
    "https://www.openstreetmap.org/?mlat=-16.5&mlon=-68.1#map=18/-16.5/-68.1",
])
def test_punto_google_maps(url):
    assert parse_map_url(url) == (Decimal("-16.5"), Decimal("-68.1"))


@pytest.mark.parametrize("url", [
    "https://evil.example/maps?q=1,2",
    "https://www.google.com.evil.example/maps?q=1,2",
    "https://www.google.com@127.0.0.1/maps?q=1,2",
    "http://www.google.com/maps?q=1,2",
    "https://www.google.com:444/maps?q=1,2",
    "https://www.google.com/maps/@1,2,15z",
    "https://www.google.com/maps?q=91,2",
    "https://www.google.com/maps?q=1,2&query=3,4",
    "https://www.google.com/maps?q=plaza",
    "https://www.google.com/maps/dir/?query=1,2",
    "https://www.openstreetmap.org/#map=18/1/2",
    "https://www.google.com/maps/place/casa#data=!3d1!4d2",
    "https://www.google.com/maps/place/casa?query=1,2",
    "https://www.google.com/maps/place/casa/data=!3d1!4d2invalido",
])
def test_enlaces_invalidos_no_se_interpretan(url):
    with pytest.raises(ValueError):
        resolve_map_url(url)


def test_enlace_corto_y_redireccion_peligrosa(monkeypatch):
    monkeypatch.setattr("app.enlaces_gps.redirect_location", lambda _: "https://www.google.com/maps?q=1,2")
    assert resolve_map_url("https://maps.app.goo.gl/abc") == (Decimal(1), Decimal(2))
    monkeypatch.setattr("app.enlaces_gps.redirect_location", lambda _: "https://127.0.0.1/admin")
    with pytest.raises(ValueError):
        resolve_map_url("https://maps.app.goo.gl/abc")


def test_dns_privado_es_rechazado_antes_de_conectar(monkeypatch):
    monkeypatch.setattr("app.enlaces_gps.socket.getaddrinfo", lambda *args, **kwargs: [(0, 0, 0, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="no permitida"):
        resolve_map_url("https://maps.app.goo.gl/abc")


def test_redireccion_usa_ip_publica_valida_y_servidor_permitido(monkeypatch):
    observed = []
    monkeypatch.setattr("app.enlaces_gps.socket.getaddrinfo", lambda *args, **kwargs: [(0, 0, 0, "", ("8.8.8.8", 443))])

    class Response:
        status = 302

        def getheader(self, name):
            return "https://www.google.com/maps?q=1,2" if name == "Location" else None

    class Connection:
        def __init__(self, host, address):
            observed.append((host, address))

        def request(self, method, path, headers):
            observed.append((method, path))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("app.enlaces_gps.PinnedHTTPSConnection", Connection)
    assert resolve_map_url("https://maps.app.goo.gl/abc") == (Decimal(1), Decimal(2))
    assert observed == [("maps.app.goo.gl", "8.8.8.8"), ("GET", "/abc")]
