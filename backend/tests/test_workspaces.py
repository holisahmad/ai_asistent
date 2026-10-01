"""Contract tests workspace & RBAC (termasuk isolasi antar workspace)."""

import uuid

WS = "/api/v1/workspaces"


def _create(client, headers, name="WS"):  # noqa: ANN001, ANN202
    slug = f"ws-{uuid.uuid4().hex[:8]}"
    return client.post(WS, headers=headers, json={"name": name, "slug": slug})


def test_create_workspace_makes_creator_admin(client, user_headers) -> None:  # noqa: ANN001
    resp = _create(client, user_headers)
    assert resp.status_code == 201
    wid = resp.json()["id"]

    detail = client.get(f"{WS}/{wid}", headers=user_headers)
    assert detail.status_code == 200
    members = detail.json()["members"]
    assert len(members) == 1
    assert members[0]["role"] == "admin"
    assert members[0]["email"] == "alice@example.com"


def test_duplicate_slug_conflict(client, user_headers) -> None:  # noqa: ANN001
    slug = f"ws-{uuid.uuid4().hex[:8]}"
    first = client.post(WS, headers=user_headers, json={"name": "A", "slug": slug})
    assert first.status_code == 201
    second = client.post(WS, headers=user_headers, json={"name": "B", "slug": slug})
    assert second.status_code == 409


def test_list_workspaces_only_own(client, user_headers, second_user_headers) -> None:  # noqa: ANN001
    _create(client, user_headers, "Milik Alice")
    _create(client, second_user_headers, "Milik Bob")

    alice_ws = client.get(WS, headers=user_headers).json()
    bob_ws = client.get(WS, headers=second_user_headers).json()
    assert [w["name"] for w in alice_ws] == ["Milik Alice"]
    assert [w["name"] for w in bob_ws] == ["Milik Bob"]


def test_non_member_gets_404_not_403(client, user_headers, second_user_headers) -> None:  # noqa: ANN001
    """Isolasi tenant: workspace orang lain terlihat sebagai 404 (anti enumeration)."""
    wid = _create(client, user_headers).json()["id"]
    assert client.get(f"{WS}/{wid}", headers=second_user_headers).status_code == 404


def test_role_hierarchy_enforced(client, user_headers, second_user_headers) -> None:  # noqa: ANN001
    """admin > editor > contributor > viewer; endpoint admin menolak role rendah."""
    wid = _create(client, user_headers).json()["id"]

    # Tambah Bob sebagai viewer
    added = client.post(
        f"{WS}/{wid}/members",
        headers=user_headers,
        json={"email": "bob@example.com", "role": "viewer"},
    )
    assert added.status_code == 201

    # Viewer boleh lihat detail
    assert client.get(f"{WS}/{wid}", headers=second_user_headers).status_code == 200
    # Viewer tidak boleh tambah anggota (butuh admin)
    denied = client.post(
        f"{WS}/{wid}/members",
        headers=second_user_headers,
        json={"email": "c@x.com", "role": "viewer"},
    )
    assert denied.status_code == 403
    # Viewer tidak boleh update nama workspace
    denied_patch = client.patch(
        f"{WS}/{wid}", headers=second_user_headers, json={"name": "Baru"}
    )
    assert denied_patch.status_code == 403


def test_contributor_can_read_but_not_admin(client, user_headers, second_user_headers) -> None:  # noqa: ANN001
    wid = _create(client, user_headers).json()["id"]
    client.post(
        f"{WS}/{wid}/members",
        headers=user_headers,
        json={"email": "bob@example.com", "role": "contributor"},
    )
    assert client.get(f"{WS}/{wid}", headers=second_user_headers).status_code == 200
    assert (
        client.patch(f"{WS}/{wid}", headers=second_user_headers, json={"name": "X"}).status_code
        == 403
    )


def test_cannot_remove_last_admin(client, user_headers) -> None:  # noqa: ANN001
    wid = _create(client, user_headers).json()["id"]
    alice_id = client.get("/api/v1/auth/me", headers=user_headers).json()["id"]
    resp = client.delete(f"{WS}/{wid}/members/{alice_id}", headers=user_headers)
    assert resp.status_code == 409


def test_add_member_requires_admin(client, user_headers, second_user_headers) -> None:  # noqa: ANN001
    """User non-anggota sama sekali tidak bisa menambah anggota (404)."""
    wid = _create(client, user_headers).json()["id"]
    resp = client.post(
        f"{WS}/{wid}/members",
        headers=second_user_headers,
        json={"email": "bob@example.com", "role": "viewer"},
    )
    assert resp.status_code == 404


def test_remove_member_flow(client, user_headers, second_user_headers) -> None:  # noqa: ANN001
    wid = _create(client, user_headers).json()["id"]
    client.post(
        f"{WS}/{wid}/members",
        headers=user_headers,
        json={"email": "bob@example.com", "role": "viewer"},
    )
    bob_id = client.get("/api/v1/auth/me", headers=second_user_headers).json()["id"]
    assert (
        client.delete(f"{WS}/{wid}/members/{bob_id}", headers=user_headers).status_code == 204
    )
    # Bob bukan anggota lagi -> 404
    assert client.get(f"{WS}/{wid}", headers=second_user_headers).status_code == 404
