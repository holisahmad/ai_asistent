"""Contract tests endpoint auth."""

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"


def test_register_returns_token_and_me_works(client) -> None:  # noqa: ANN001
    resp = client.post(
        REGISTER, json={"email": "a@x.com", "name": "A", "password": "password123"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token"]
    assert body["expires_at"]

    me = client.get(ME, headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "a@x.com"


def test_register_duplicate_email_conflict(client) -> None:  # noqa: ANN001
    payload = {"email": "dup@x.com", "name": "D", "password": "password123"}
    assert client.post(REGISTER, json=payload).status_code == 201
    assert client.post(REGISTER, json=payload).status_code == 409


def test_register_weak_password_rejected(client) -> None:  # noqa: ANN001
    resp = client.post(REGISTER, json={"email": "w@x.com", "name": "W", "password": "short"})
    assert resp.status_code == 422


def test_login_success_and_wrong_password(client) -> None:  # noqa: ANN001
    client.post(REGISTER, json={"email": "l@x.com", "name": "L", "password": "password123"})

    ok = client.post(LOGIN, json={"email": "l@x.com", "password": "password123"})
    assert ok.status_code == 200
    assert ok.json()["token"]

    bad = client.post(LOGIN, json={"email": "l@x.com", "password": "wrong-password"})
    assert bad.status_code == 401


def test_login_unknown_email_is_401(client) -> None:  # noqa: ANN001
    resp = client.post(LOGIN, json={"email": "ghost@x.com", "password": "whatever123"})
    assert resp.status_code == 401


def test_logout_revokes_token(client) -> None:  # noqa: ANN001
    token = client.post(
        REGISTER, json={"email": "o@x.com", "name": "O", "password": "password123"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.post(LOGOUT, headers=headers).status_code == 204
    assert client.get(ME, headers=headers).status_code == 401


def test_me_requires_auth(client) -> None:  # noqa: ANN001
    assert client.get(ME).status_code == 401
