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
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from flask import current_app, redirect, request

if TYPE_CHECKING:
    from flask import Flask, Response

logger = logging.getLogger(__name__)

TOKEN_QUERY_PARAM = "token"
SKIP_PATH_PREFIXES = ("/static/", "/api/", "/ws")
# Browsers reject cookies larger than ~4096 bytes.
MAX_SESSION_COOKIE_BYTES = 4093
DEFAULT_REDIRECT_AFTER_TOKEN = "/alpha/welcome/"


def normalize_session_cookie_value(token: str) -> str:
    """
    Flask signed session cookies start with a single "." (itsdangerous format).
    Accept ?token=eJwl... or ?token=.eJwl... or ?token=..eJwl... from partners.
    """
    token = token.strip()
    if not token:
        return token
    payload = token.lstrip(".")
    if not payload:
        return token
    return f".{payload}"


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


def get_redirect_target() -> str:
    """
    After applying the session cookie, land on the app home instead of /login.
    Keeps non-token query params when redirecting from non-login pages.
    """
    redirect_path = current_app.config.get(
        "URL_TOKEN_LOGIN_REDIRECT", DEFAULT_REDIRECT_AFTER_TOKEN
    )
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
    samesite = app.config.get("SESSION_COOKIE_SAMESITE")
    response.set_cookie(
        app.session_cookie_name,
        token,
        httponly=app.config.get("SESSION_COOKIE_HTTPONLY", True),
        secure=app.config.get("SESSION_COOKIE_SECURE", False),
        samesite=samesite if samesite else None,
        domain=app.config.get("SESSION_COOKIE_DOMAIN"),
        path=app.config.get("SESSION_COOKIE_PATH") or "/",
    )


def handle_url_token_login() -> Response | None:
    try:
        token = request.args.get(TOKEN_QUERY_PARAM)
        if not token:
            return None

        if any(request.path.startswith(prefix) for prefix in SKIP_PATH_PREFIXES):
            return None

        session_value = normalize_session_cookie_value(token)
        if len(session_value.encode("utf-8")) > MAX_SESSION_COOKIE_BYTES:
            logger.error(
                "URL token login: token too long for session cookie (%s bytes)",
                len(session_value.encode("utf-8")),
            )
            return redirect(build_url_without_token())

        target = get_redirect_target()
        logger.info(
            "URL token login: applying session cookie, redirect to %s",
            target,
        )
        if session_value != token.strip():
            logger.info("URL token login: normalized token to Flask session format")

        response = redirect(target)
        set_session_cookie(response, session_value)
        return response
    except Exception:  # pylint: disable=broad-except
        logger.exception("URL token login failed")
        try:
            return redirect(build_url_without_token())
        except Exception:  # pylint: disable=broad-except
            return redirect(DEFAULT_REDIRECT_AFTER_TOKEN)


def register_url_token_login(app: Flask) -> None:
    @app.before_request
    def url_token_login_before_request() -> Response | None:
        return handle_url_token_login()
