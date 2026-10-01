"""Contract tests file endpoints (Fase 3) — butuh Postgres + MinIO test."""

import uuid
from io import BytesIO
from typing import Any

import pytest

WS = "/api/v1/workspaces"

Headers = dict[str, str]
OwnedWS = tuple[Headers, str]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mk_user(client: Any, email: str) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": email.split("@")[0], "password": "password123"},
    )
    return _headers(r.json()["token"])


def _mk_ws(client: Any, headers: dict[str, str]) -> str:
    r = client.post(WS, headers=headers, json={"name": "WS", "slug": f"ws-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201
    return r.json()["id"]


def _upload(client: Any, headers: dict[str, str], ws_id: str, name: str, content: bytes):
    return client.post(
        f"{WS}/{ws_id}/files",
        headers=headers,
        files={"file": (name, BytesIO(content), "application/octet-stream")},
    )


@pytest.fixture(name="alice_ws")
def alice_ws_fixture(client: Any) -> tuple[dict[str, str], str]:
    headers = _mk_user(client, "alice@example.com")
    return headers, _mk_ws(client, headers)


def test_upload_success_and_detail(client: Any, alice_ws: OwnedWS) -> None:
    headers, ws_id = alice_ws
    r = _upload(client, headers, ws_id, "notes.txt", b"halo dunia")
    assert r.status_code == 201
    body = r.json()
    assert body["filename"] == "notes.txt"
    assert body["status"] == "queued"
    assert body["current_version"] == 1
    assert len(body["checksum_sha256"]) == 64

    detail = client.get(f"{WS}/{ws_id}/files/{body['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == body["id"]


def test_upload_dedup_conflict(client: Any, alice_ws: OwnedWS) -> None:
    headers, ws_id = alice_ws
    assert _upload(client, headers, ws_id, "a.txt", b"sama").status_code == 201
    assert _upload(client, headers, ws_id, "b.txt", b"sama").status_code == 409


def test_upload_rejected_extension_and_empty(client: Any, alice_ws: OwnedWS) -> None:
    headers, ws_id = alice_ws
    assert _upload(client, headers, ws_id, "virus.exe", b"x").status_code == 415
    assert _upload(client, headers, ws_id, "empty.txt", b"").status_code == 400


def test_upload_requires_contributor_role(client: Any) -> None:
    owner = _mk_user(client, "owner@example.com")
    viewer = _mk_user(client, "viewer@example.com")
    ws_id = _mk_ws(client, owner)
    client.post(
        f"{WS}/{ws_id}/members",
        headers=owner,
        json={"email": "viewer@example.com", "role": "viewer"},
    )
    assert _upload(client, viewer, ws_id, "x.txt", b"data").status_code == 403


def test_non_member_cannot_list_or_see_files(client: Any, alice_ws: OwnedWS) -> None:
    headers, ws_id = alice_ws
    fid = _upload(client, headers, ws_id, "rahasia.txt", b"top secret").json()["id"]
    outsider = _mk_user(client, "outsider@example.com")
    assert client.get(f"{WS}/{ws_id}/files", headers=outsider).status_code == 404
    assert client.get(f"{WS}/{ws_id}/files/{fid}", headers=outsider).status_code == 404
    # Isolasi lintas-workspace: file workspace lain tidak terlihat walau user anggota di tempat lain
    other_owner = _mk_user(client, "other@example.com")
    other_ws = _mk_ws(client, other_owner)
    assert client.get(f"{WS}/{other_ws}/files/{fid}", headers=other_owner).status_code == 404


def test_list_with_status_filter(client: Any, alice_ws: OwnedWS) -> None:
    headers, ws_id = alice_ws
    _upload(client, headers, ws_id, "f1.txt", b"isi satu")
    queued = client.get(f"{WS}/{ws_id}/files?status=queued", headers=headers)
    assert queued.status_code == 200
    assert len(queued.json()) == 1
    bad = client.get(f"{WS}/{ws_id}/files?status=ngawur", headers=headers)
    assert bad.status_code == 400


def test_cancel_then_reindex_flow(client: Any, alice_ws: OwnedWS) -> None:
    headers, ws_id = alice_ws
    fid = _upload(client, headers, ws_id, "c.txt", b"cancel me").json()["id"]

    assert client.post(f"{WS}/{ws_id}/files/{fid}/cancel", headers=headers).status_code == 200
    body = client.get(f"{WS}/{ws_id}/files/{fid}", headers=headers).json()
    assert body["status"] == "deleted"

    # reindex menghidupkan kembali ke queued
    assert client.post(f"{WS}/{ws_id}/files/{fid}/reindex", headers=headers).status_code == 200
    assert client.get(f"{WS}/{ws_id}/files/{fid}", headers=headers).json()["status"] == "queued"
    # reindex saat queued → 409
    assert client.post(f"{WS}/{ws_id}/files/{fid}/reindex", headers=headers).status_code == 409
    # cancel saat queued → boleh
    assert client.post(f"{WS}/{ws_id}/files/{fid}/cancel", headers=headers).status_code == 200


def test_delete_soft_hides_file(client: Any, alice_ws: OwnedWS) -> None:
    headers, ws_id = alice_ws
    fid = _upload(client, headers, ws_id, "d.txt", b"delete me").json()["id"]
    assert client.delete(f"{WS}/{ws_id}/files/{fid}", headers=headers).status_code == 200
    assert client.get(f"{WS}/{ws_id}/files/{fid}", headers=headers).status_code == 404
    # dedup tidak menghitung file terhapus
    assert _upload(client, headers, ws_id, "d2.txt", b"delete me").status_code == 201


def test_delete_requires_editor_role(client: Any) -> None:
    owner = _mk_user(client, "own@example.com")
    contrib = _mk_user(client, "contrib@example.com")
    ws_id = _mk_ws(client, owner)
    client.post(
        f"{WS}/{ws_id}/members",
        headers=owner,
        json={"email": "contrib@example.com", "role": "contributor"},
    )
    fid = _upload(client, contrib, ws_id, "x.txt", b"data").json()["id"]
    assert client.delete(f"{WS}/{ws_id}/files/{fid}", headers=contrib).status_code == 403


def test_download_returns_presigned_redirect(client: Any, alice_ws: OwnedWS) -> None:
    headers, ws_id = alice_ws
    fid = _upload(client, headers, ws_id, "dl.txt", b"download me").json()["id"]
    r = client.get(f"{WS}/{ws_id}/files/{fid}/download", headers=headers, follow_redirects=False)
    assert r.status_code == 307
    assert "localhost:9000" in r.headers["location"]
    assert "X-Amz-Signature" in r.headers["location"]
