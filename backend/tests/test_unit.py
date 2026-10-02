from __future__ import annotations

import logging

import pytest
from sqlalchemy import text

from app.content.similarity import cosine, lexical_similarity
from app.core.crypto import mask_secret
from app.core.logging import RedactingFilter, redact
from app.models.enums import ProxyScheme
from app.models.proxy import Proxy
from app.openai.agents.editor import local_cleanup
from app.openai.pricing import estimate_cost
from app.proxy.parser import ProxyParseError, parse_proxy, parse_proxy_list


@pytest.mark.parametrize("line,expected", [
    ("1.2.3.4:8080", ("http", "1.2.3.4", 8080, None, None)),
    ("1.2.3.4:8080:login", ("http", "1.2.3.4", 8080, "login", None)),
    ("1.2.3.4:8080:login:pass", ("http", "1.2.3.4", 8080, "login", "pass")),
    ("login@1.2.3.4", ("http", "1.2.3.4", 8080, "login", None)),
    ("login@1.2.3.4:3128", ("http", "1.2.3.4", 3128, "login", None)),
    ("login:pass@1.2.3.4:3128", ("http", "1.2.3.4", 3128, "login", "pass")),
    ("http://login:p%40ss@1.2.3.4:3128", ("http", "1.2.3.4", 3128, "login", "p@ss")),
    ("https://1.2.3.4:443", ("https", "1.2.3.4", 443, None, None)),
    ("socks5://login@5.6.7.8", ("socks5", "5.6.7.8", 1080, "login", None)),
    ("socks5h://u:p@proxy.example.com:9050", ("socks5", "proxy.example.com", 9050, "u", "p")),
])
def test_proxy_formats(line, expected):
    p = parse_proxy(line)
    assert (p.scheme.value, p.host, p.port, p.username, p.password) == expected


@pytest.mark.parametrize("line", ["", "ftp://1.2.3.4:21", "1.2.3.4:99999", "not a host", "1.2.3.4:port"])
def test_proxy_invalid(line):
    with pytest.raises(ProxyParseError):
        parse_proxy(line)


def test_proxy_list_dedup_and_errors_do_not_leak_passwords():
    result = parse_proxy_list("1.1.1.1:80\n1.1.1.1:80\n# comment\nu:secretpw@bad host:1\n")
    assert len(result.proxies) == 1
    assert len(result.errors) == 1
    assert "secretpw" not in str(result.errors)


def test_proxy_url_and_default_scheme():
    p = Proxy(scheme=ProxyScheme.SOCKS5.value, host="h.example.com", port=1080, username="u@x", password="p:w")
    assert p.url() == "socks5://u%40x:p%3Aw@h.example.com:1080"
    assert "p:w" not in p.display()
    assert parse_proxy("1.2.3.4:1", ProxyScheme.SOCKS5).scheme == ProxyScheme.SOCKS5


def test_secrets_encrypted_at_rest(db):
    from app.models.vk_account import VKAccount

    account = VKAccount(name="a", access_token="vk1.a.SUPERSECRET", info={}, groups_cache=[])
    db.add(account)
    db.commit()
    raw = db.execute(text("SELECT access_token FROM vk_accounts WHERE id = :id"), {"id": account.id}).scalar_one()
    assert "SUPERSECRET" not in raw
    db.expire_all()
    assert db.get(VKAccount, account.id).access_token == "vk1.a.SUPERSECRET"
    assert "SUPERSECRET" not in repr(account)


def test_mask_secret():
    assert mask_secret("password123") == "pa******23"
    assert mask_secret("abc") == "********"
    assert mask_secret(None) is None


def test_redaction():
    assert "abc123" not in redact("access_token=abc123&v=5.199")
    assert "secret" not in redact("http://user:secret@1.2.3.4:80")
    assert "vk1.a.xyz" not in redact("token vk1.a.xyzXYZ")
    assert "sk-proj" not in redact("key sk-projABCDEFGHIJKLMN")
    record = logging.LogRecord("x", logging.INFO, "f", 1, "call with %s", ("access_token=zzz",), None)
    RedactingFilter().filter(record)
    assert "zzz" not in record.getMessage()


def test_cost_estimation():
    pricing = {"m": {"input": 1.0, "cached_input": 0.1, "output": 2.0}}
    assert estimate_cost("m", 1_000_000, 1_000_000, 0, pricing) == 3.0
    assert estimate_cost("m", 1_000_000, 0, 1_000_000, pricing) == 0.1
    assert estimate_cost("m-2026-01-01", 1_000_000, 0, 0, pricing) == 1.0
    assert estimate_cost("unknown", 1000, 1000, 0, pricing) == 0.0


def test_similarity_helpers():
    assert lexical_similarity("Как выбрать диван", "Как выбрать диван?") > 0.9
    assert lexical_similarity("Как выбрать диван", "Акция на кухни") < 0.5
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)


def test_editor_local_cleanup():
    text, found = local_cleanup("В современном мире все спешат. **Важно**: не секрет, что мы лучшие.\n## Итог")
    assert "современном мире" not in text.lower()
    assert "не секрет" not in text.lower()
    assert "**" not in text and "##" not in text
    assert len(found) == 2


def test_settings_parse_env_formats(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", "http://a.example, http://b.example")
    monkeypatch.setenv("AI_MODEL_OVERRIDES", '{"project_setup": "gpt-5.4"}')
    s = Settings(_env_file=None)
    assert s.CORS_ORIGINS == ["http://a.example", "http://b.example"]
    assert s.AI_MODEL_OVERRIDES == {"project_setup": "gpt-5.4"}
    monkeypatch.setenv("CORS_ORIGINS", '["http://c.example"]')
    assert Settings(_env_file=None).CORS_ORIGINS == ["http://c.example"]
