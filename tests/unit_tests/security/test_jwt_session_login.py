# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask

from superset.utils.jwt_session_login import (
    is_safe_redirect_path,
    resolve_session_login_redirect,
    UnsafeRedirectError,
)


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/alpha/welcome/", True),
        ("/superset/welcome", True),
        ("/", True),
        (None, False),
        ("", False),
        ("https://evil.com/", False),
        ("//evil.com/path", False),
        ("/\\evil", False),
        ("alpha/welcome", False),
        ("javascript:alert(1)", False),
    ],
)
def test_is_safe_redirect_path(path: str | None, expected: bool) -> None:
    assert is_safe_redirect_path(path) is expected


def test_resolve_uses_requested_safe_path(app_context: None) -> None:
    assert resolve_session_login_redirect("/dashboards/list/") == "/dashboards/list/"


def test_resolve_rejects_unsafe_requested_path(app_context: None) -> None:
    with pytest.raises(UnsafeRedirectError):
        resolve_session_login_redirect("https://evil.example/")


def test_resolve_falls_back_to_config(app: Flask) -> None:
    app.config["JWT_SESSION_LOGIN_REDIRECT"] = "/custom/home/"
    with app.app_context():
        assert resolve_session_login_redirect(None) == "/custom/home/"


def test_create_session_success(app: Flask, mocker) -> None:
    user = SimpleNamespace(id=1, username="admin", active=True, is_anonymous=False)
    mocker.patch("superset.security.api.verify_jwt_in_request", return_value=True)
    mocker.patch("superset.security.api.get_jwt_identity", return_value=1)
    mock_login = mocker.patch("superset.security.api.login_user")
    mock_sm = MagicMock()
    mock_sm.load_user.return_value = user

    from superset.security.api import SecurityRestApi

    api = SecurityRestApi()
    api.appbuilder = SimpleNamespace(sm=mock_sm)  # type: ignore[attr-defined]

    with app.test_request_context(
        "/api/v1/security/session",
        method="POST",
        json={"redirect": "/alpha/welcome/"},
        headers={"Authorization": "Bearer fake"},
    ):
        response = api.create_session()

    assert response.status_code == 200
    payload = json.loads(response.data.decode("utf-8"))
    assert payload["redirect"] == "/alpha/welcome/"
    mock_login.assert_called_once_with(user, remember=False)
    mock_sm.load_user.assert_called()


def test_create_session_unauthorized_without_jwt(app: Flask, mocker) -> None:
    mocker.patch(
        "superset.security.api.verify_jwt_in_request",
        side_effect=Exception("no auth"),
    )
    from superset.security.api import SecurityRestApi

    api = SecurityRestApi()
    api.appbuilder = SimpleNamespace(sm=MagicMock())  # type: ignore[attr-defined]

    with app.test_request_context("/api/v1/security/session", method="POST"):
        response = api.create_session()

    assert response.status_code == 401


def test_create_session_invalid_redirect(app: Flask, mocker) -> None:
    user = SimpleNamespace(id=1, username="admin", active=True, is_anonymous=False)
    mocker.patch("superset.security.api.verify_jwt_in_request", return_value=True)
    mocker.patch("superset.security.api.get_jwt_identity", return_value=1)
    mocker.patch("superset.security.api.login_user")
    mock_sm = MagicMock()
    mock_sm.load_user.return_value = user

    from superset.security.api import SecurityRestApi

    api = SecurityRestApi()
    api.appbuilder = SimpleNamespace(sm=mock_sm)  # type: ignore[attr-defined]

    with app.test_request_context(
        "/api/v1/security/session",
        method="POST",
        json={"redirect": "https://evil.example/"},
        headers={"Authorization": "Bearer fake"},
    ):
        response = api.create_session()

    assert response.status_code == 400
