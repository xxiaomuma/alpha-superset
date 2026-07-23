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

from urllib.parse import urlparse

from flask import current_app

from superset.utils.url_token_login import (
    DEFAULT_REDIRECT_AFTER_TOKEN,
    get_default_redirect_path,
)


class UnsafeRedirectError(ValueError):
    """Raised when a client-supplied redirect target is not a safe relative path."""


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
