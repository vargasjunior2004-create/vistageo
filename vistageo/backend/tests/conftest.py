import os

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-geo-vista-0123456789abcdef")
os.environ.setdefault("JWT_ISSUER", "geo-vista-test")
os.environ.setdefault("JWT_AUDIENCE", "geo-vista-test-api")
os.environ.setdefault("LOGIN_RATE_LIMIT_IP", "1000")
os.environ.setdefault("LOGIN_RATE_LIMIT_ACCOUNT", "1000")

from app.rate_limit import limiter


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    limiter.clear()
    yield
    limiter.clear()
