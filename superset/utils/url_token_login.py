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

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from flask import current_app, redirect, request, session

if TYPE_CHECKING:
    from flask import Flask, Response

logger = logging.getLogger(__name__)

TOKEN_QUERY_PARAM = "token"
SKIP_PATH_PREFIXES = ("/static/", "/api/", "/ws")
# Browsers reject cookies larger than ~4096 bytes.
MAX_SESSION_COOKIE_BYTES = 4093
DEFAULT_REDIRECT_AFTER_TOKEN = "/alpha/welcome/"


def session_cookie_candidates(token: str) -> list[str]:
    """Return likely Flask session cookie values for a URL token."""
    token = token.strip()
    if not token:
        return []

    payload = token.lstrip(".")
    candidates = [token]
    if payload and payload not in candidates:
        candidates.append(payload)
    if not token.startswith("."):
        candidates.append(f".{payload}")
    return candidates


def parse_session_token(app: Flask, token: str) -> dict[str, Any] | None:
    """Decode a signed session token using Superset's session serializer."""
    serializer = app.session_interface.get_signing_serializer(app)
    if serializer is None:
        return None

    max_age = int(app.permanent_session_lifetime.total_seconds())
    for candidate in session_cookie_candidates(token):
        try:
            data = serializer.loads(candidate, max_age=max_age)
        except Exception:  # pylint: disable=broad-except
            continue
        if isinstance(data, dict):
            return data
    return None


def build_url_without_token() -> str:
    parsed = urlparse(request.url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != TOKEN_QUERY_PARAM
    ]
    if query:
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(query),
                parsed.fragment,
            )
        )
    return parsed.path or "/"


def get_default_redirect_path() -> str:
    return (
        current_app.config.get("URL_TOKEN_LOGIN_REDIRECT")
        or current_app.config.get("LOGO_TARGET_PATH")
        or DEFAULT_REDIRECT_AFTER_TOKEN
    )


def get_redirect_target() -> str:
    """
    After applying the session cookie, land on the app home instead of /login.
    Keeps non-token query params when redirecting from non-login pages.
    """
    redirect_path = get_default_redirect_path()
    if request.path.startswith("/login"):
        return redirect_path

    clean_url = build_url_without_token()
    parsed = urlparse(clean_url)
    if parsed.path in ("/", "/login", "/login/"):
        return redirect_path
    return clean_url


def set_session_cookie(response: Response, token: str) -> None:
    """Set the session cookie using the same options as a normal Flask login."""
    app = current_app
    domain = app.config.get("SESSION_COOKIE_DOMAIN") or None
    samesite = app.config.get("SESSION_COOKIE_SAMESITE") or None
    response.set_cookie(
        app.session_cookie_name,
        token,
        httponly=app.config.get("SESSION_COOKIE_HTTPONLY", True),
        secure=app.config.get("SESSION_COOKIE_SECURE", False),
        samesite=samesite,
        domain=domain,
        path=app.config.get("SESSION_COOKIE_PATH") or "/",
    )


def apply_session_from_token(response: Response, token: str) -> bool:
    """
    Persist the token as a session cookie.

    Prefer Flask's session interface so the cookie format matches login exactly.
    Fall back to raw Set-Cookie when the token cannot be decoded locally.
    """
    app = current_app
    session_data = parse_session_token(app, token)
    if session_data is not None:
        session.clear()
        session.update(session_data)
        app.session_interface.save_session(app, session, response)
        return True

    for candidate in session_cookie_candidates(token):
        if len(candidate.encode("utf-8")) > MAX_SESSION_COOKIE_BYTES:
            continue
        try:
            set_session_cookie(response, candidate)
            return True
        except Exception:  # pylint: disable=broad-except
            logger.debug(
                "URL token login: set_cookie failed for candidate prefix=%s",
                candidate[:16],
                exc_info=True,
            )
    return False


def handle_url_token_login() -> Response | None:
    token = request.args.get(TOKEN_QUERY_PARAM)
    if not token:
        return None

    if any(request.path.startswith(prefix) for prefix in SKIP_PATH_PREFIXES):
        return None

    try:
        if len(token.encode("utf-8")) > MAX_SESSION_COOKIE_BYTES:
            logger.error(
                "URL token login: token too long for session cookie (%s bytes)",
                len(token.encode("utf-8")),
            )
            return redirect(build_url_without_token())

        target = get_redirect_target()
        response = redirect(target)
        if apply_session_from_token(response, token):
            logger.info(
                "URL token login: session cookie applied, redirect to %s",
                target,
            )
            return response

        logger.error("URL token login: unable to apply session cookie")
        return redirect(build_url_without_token())
    except Exception:  # pylint: disable=broad-except
        logger.exception("URL token login failed")
        try:
            return redirect(build_url_without_token())
        except Exception:  # pylint: disable=broad-except
            return redirect(get_default_redirect_path())


def register_url_token_login(app: Flask) -> None:
    @app.before_request
    def url_token_login_before_request() -> Response | None:
        return handle_url_token_login()
