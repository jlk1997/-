"""Tests for legal consent and content moderation."""

from app.services.content_moderation import check_content_moderation
from app.services.legal import get_required_versions, list_documents, require_registration_consents


def test_list_documents():
    docs = list_documents()
    assert len(docs) >= 6
    slugs = {d["slug"] for d in docs}
    assert "privacy-policy" in slugs
    assert "terms-of-service" in slugs


def test_list_documents_en_titles_keep_zh_versions():
    zh_docs = list_documents("zh")
    en_docs = list_documents("en")
    zh_versions = {d["slug"]: d["version"] for d in zh_docs}
    en_versions = {d["slug"]: d["version"] for d in en_docs}
    assert zh_versions == en_versions
    titles = {d["slug"]: d["title"] for d in en_docs}
    assert titles["privacy-policy"] == "Privacy Policy"
    assert titles["distribution-license"] == "Distribution & split agreement"


def test_required_versions():
    versions = get_required_versions()
    assert "terms" in versions
    assert "privacy" in versions


def test_content_moderation_blocks():
    assert check_content_moderation("正常音乐分享") is None
    assert check_content_moderation("赌博网站推广") is not None


def test_registration_consents_valid():
    versions = get_required_versions()
    require_registration_consents(versions["terms"], versions["privacy"])


def test_legal_documents_api():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    res = client.get("/api/v1/legal/documents")
    assert res.status_code == 200
    data = res.json()
    assert len(data["documents"]) >= 6

    slug_res = client.get("/api/v1/legal/documents/privacy-policy")
    assert slug_res.status_code == 200
    assert "content" in slug_res.json()

    en_res = client.get("/api/v1/legal/documents/privacy-policy", params={"locale": "en"})
    assert en_res.status_code == 200
    en_doc = en_res.json()
    assert en_doc["title"] == "Privacy Policy"
    assert en_doc["locale"] == "en"
    assert "BitYin" in en_doc["content"]
    assert "微信小程序及相关产品" not in en_doc["content"]
    assert en_doc["content"] != slug_res.json()["content"]
    assert en_doc["version"] == slug_res.json()["version"]

    en_list = client.get("/api/v1/legal/documents", params={"locale": "en"})
    assert en_list.status_code == 200
    titles = {d["slug"]: d["title"] for d in en_list.json()["documents"]}
    assert titles["privacy-policy"] == "Privacy Policy"
    assert titles["terms-of-service"] == "Terms of Service"

    for doc in en_list.json()["documents"]:
        body = client.get(f"/api/v1/legal/documents/{doc['slug']}", params={"locale": "en"})
        assert body.status_code == 200
        payload = body.json()
        assert payload["locale"] == "en"
        assert payload["version"] == doc["version"]

    fallback = client.get("/api/v1/legal/documents/privacy-policy", params={"locale": "fr"})
    assert fallback.status_code == 200
    assert fallback.json()["title"] == slug_res.json()["title"]

    meta_res = client.get("/api/v1/legal/meta")
    assert meta_res.status_code == 200
    meta = meta_res.json()
    assert "required_versions" in meta
    assert "contact_email" in meta
