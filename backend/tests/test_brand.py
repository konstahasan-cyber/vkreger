from __future__ import annotations

import httpx
import pytest

from app.content.brand_import import BrandImportError, _assert_public_host, fetch_site, parse_html
from tests.helpers import setup_project_with_community

HTML = """<html><head><title>Зерно — кофейня</title><meta name="theme-color" content="#C0392B">
<meta name="description" content="Свежая обжарка"><link rel="stylesheet" href="/main.css">
<style>body{font-family:'Montserrat',sans-serif;color:#333}.btn{background:#c0392b}</style></head>
<body><img src="/logo.svg" alt="Зерно logo"><h1>Кофе с собой</h1><p>Капучино от 150 рублей, ул. Баумана 1</p>
<script>var secret=1</script></body></html>"""


def test_parse_html_extracts_brand_signals():
    signals, css_links = parse_html(HTML, "https://zerno.example/")
    assert signals.colors[0] == "#c0392b"
    assert signals.fonts == ["Montserrat"]
    assert signals.logo_url == "https://zerno.example/logo.svg"
    assert "Капучино" in signals.text and "secret" not in signals.text
    assert css_links == ["/main.css"]


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8000/", "http://10.0.0.5/", "ftp://x.ru"])
def test_ssrf_guard(url):
    with pytest.raises(BrandImportError):
        _assert_public_host(url)


def test_fetch_site_reads_linked_css(monkeypatch):
    monkeypatch.setattr("app.content.brand_import._assert_public_host", lambda url: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/main.css":
            return httpx.Response(200, text=".hero{background:#1abc9c}.x{color:#1abc9c}.y{color:#1abc9c}")
        return httpx.Response(200, text=HTML)

    signals = fetch_site("zerno.example", transport=httpx.MockTransport(handler))
    assert "#1abc9c" in signals.colors


@pytest.fixture
def project(client, admin_headers, vk):
    return setup_project_with_community(client, admin_headers, vk)


def test_brand_upload_design_and_vk_upload(client, admin_headers, vk, project):
    pid = project["id"]
    files = {"file": ("site.html", HTML.encode(), "text/html")}
    job = client.post(f"/api/projects/{pid}/brand/upload", files=files, headers=admin_headers).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=admin_headers).json()
    assert job["status"] == "success", job
    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    style = detail["brand"]["style"]
    assert "#c0392b" in style["palette"]
    assert style["image_style"]
    assert detail["content_rules"]["brand_tone"]

    job = client.post(f"/api/projects/{pid}/design/generate", json={"kinds": ["avatar", "cover"]},
                      headers=admin_headers).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=admin_headers).json()
    assert job["status"] == "success", job
    assert job["result"]["upload"] == {"avatar": "ok", "cover": "ok"}
    assert getattr(vk, "avatar_saved", False) and getattr(vk, "cover_saved", False)
    assert vk.cover_crop == ("1590", "530")
    brand = client.get(f"/api/projects/{pid}", headers=admin_headers).json()["brand"]
    assert brand["avatar"]["uploaded_version"] == brand["avatar"]["version"] == 1

    from PIL import Image

    assert Image.open(brand["cover"]["path"]).size == (1590, 530)


def test_post_images_use_brand_style(client, admin_headers, vk, project, db):
    from app.images.factory import set_image_provider_override
    from app.images.fake import FakeImageProvider

    prompts = []

    class Spy(FakeImageProvider):
        def generate(self, prompt, fmt):  # noqa: ANN001, ANN201
            prompts.append(prompt)
            return super().generate(prompt, fmt)

    client.post(f"/api/projects/{project['id']}/brand/upload", files={"file": ("s.html", HTML.encode(), "text/html")},
                headers=admin_headers)
    set_image_provider_override(Spy())
    try:
        job = client.post("/api/posts/generate", json={"project_id": project["id"], "topic": "Капучино"},
                          headers=admin_headers).json()
        assert client.get(f"/api/jobs/{job['id']}", headers=admin_headers).json()["status"] == "success"
    finally:
        set_image_provider_override(None)
    assert prompts and "Brand style: warm minimalist" in prompts[-1]


def test_brand_upload_rejects_garbage(client, admin_headers, vk, project):
    r = client.post(f"/api/projects/{project['id']}/brand/upload", files={"file": ("x.html", b"<html></html>", "text/html")},
                    headers=admin_headers)
    assert r.status_code == 422
