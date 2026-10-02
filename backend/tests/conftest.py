from __future__ import annotations

import os
import tempfile

from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL",
                                                     "postgresql+psycopg2://vk:vk@localhost:5432/vkreger_test"))
os.environ["AI_PROVIDER"] = "fake"
os.environ["IMAGE_PROVIDER"] = "fake"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
os.environ["MEDIA_ROOT"] = tempfile.mkdtemp(prefix="vkreger-media-")
os.environ["VK_MIN_REQUEST_INTERVAL"] = "0"
os.environ["ENCRYPTION_KEYS"] = Fernet.generate_key().decode()
os.environ["SECRET_KEY"] = "test-secret-key-with-enough-length-0123456789"
os.environ["ADMIN_EMAIL"] = ""
os.environ["PUBLIC_BASE_URL"] = "https://panel.example.com"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.rbac import Role  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.services.user_service import create_user  # noqa: E402
from app.vk.factory import set_transport_override  # noqa: E402
from tests.vk_mock import FakeVK  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def vk():
    fake = FakeVK()
    set_transport_override(fake.transport())
    yield fake
    set_transport_override(None)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _login(client: TestClient, email: str, password: str) -> dict:
    response = client.post("/api/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def client(vk):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_headers(client, db):
    create_user(db, "admin@example.com", "admin-password", Role.OWNER)
    db.commit()
    return _login(client, "admin@example.com", "admin-password")


@pytest.fixture
def viewer_headers(client, db):
    create_user(db, "viewer@example.com", "viewer-password", Role.VIEWER)
    db.commit()
    return _login(client, "viewer@example.com", "viewer-password")
