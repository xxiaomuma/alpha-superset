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
"""Helpers for exchanging a FAB JWT for a Flask browser session."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from flask import current_app
from flask_login import login_user

from superset.utils.url_token_login import (
    DEFAULT_REDIRECT_AFTER_TOKEN,
    get_default_redirect_path,
)


class UnsafeRedirectError(ValueError):
    """Raised when a client-supplied redirect target is not a safe relative path."""


class SessionLoginError(Exception):
    """Base error for JWT → session exchange failures."""

    status_code = 400


class UnauthorizedSessionLogin(SessionLoginError):
    status_code = 401


class UserNotFoundSessionLogin(SessionLoginError):
    status_code = 404


def is_safe_redirect_path(path: str | None) -> bool:
    """Return True if path is a same-origin relative URL (blocks open redirects)."""
    if not path or not isinstance(path, str):
        return False
    path = path.strip()
    if not path.startswith("/") or path.startswith("//"):
        return False
    if "\\" in path or "://" in path:
        return False
    parsed = urlparse(path)
    return not parsed.scheme and not parsed.netloc


def resolve_session_login_redirect(requested: str | None = None) -> str:
    """
    Resolve the post-login redirect path.

    Prefer an explicit safe ``requested`` path; otherwise fall back to
    ``JWT_SESSION_LOGIN_REDIRECT`` then the shared URL-token login defaults.
    """
    if requested is not None and requested != "":
        if not is_safe_redirect_path(requested):
            raise UnsafeRedirectError("redirect must be a relative path")
        return requested.strip()

    configured = current_app.config.get("JWT_SESSION_LOGIN_REDIRECT")
    if configured and is_safe_redirect_path(configured):
        return configured.strip()

    return get_default_redirect_path() or DEFAULT_REDIRECT_AFTER_TOKEN


def load_user_from_jwt_identity(security_manager: Any, identity: Any) -> Any:
    """Resolve a FAB user from a JWT identity (user id or username)."""
    user = None
    try:
        user = security_manager.load_user(identity)
    except Exception:  # pylint: disable=broad-except
        user = None
    if user is None and identity is not None:
        try:
            user = security_manager.load_user(int(identity))
        except (TypeError, ValueError, Exception):  # pylint: disable=broad-except
            user = security_manager.find_user(username=str(identity))
    return user


def establish_session_from_identity(
    security_manager: Any, identity: Any, rls_rules: list | None = None
) -> Any:
    """Validate identity, create Flask-Login session, return the user."""
    user = load_user_from_jwt_identity(security_manager, identity)
    if user is None or getattr(user, "is_anonymous", False):
        raise UserNotFoundSessionLogin("user not found")
    if hasattr(user, "active") and not user.active:
        raise UnauthorizedSessionLogin("user inactive")
    login_user(user, remember=False)
    if rls_rules:
        user._dynamic_rls = rls_rules
    return user
