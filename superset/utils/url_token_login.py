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


def normalize_session_cookie_value(token: str) -> str:
    """
    Flask session cookies from password login start with "." (itsdangerous format).
    Allow ?token= without the leading dot and normalize before Set-Cookie.
    """
    if token and not token.startswith("."):
        return f".{token}"
    return token


def build_url_without_token() -> str:
    parsed = urlparse(request.url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != TOKEN_QUERY_PARAM
    ]
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


def set_session_cookie(response: Response, token: str) -> None:
    """Set the session cookie using the same options as a normal Flask login."""
    app = current_app
    response.set_cookie(
        app.session_cookie_name,
        token,
        httponly=app.config.get("SESSION_COOKIE_HTTPONLY", True),
        secure=app.config.get("SESSION_COOKIE_SECURE", False),
        samesite=app.config.get("SESSION_COOKIE_SAMESITE"),
        domain=app.config.get("SESSION_COOKIE_DOMAIN"),
        path=app.config.get("SESSION_COOKIE_PATH") or "/",
    )


def handle_url_token_login() -> Response | None:
    token = request.args.get(TOKEN_QUERY_PARAM)
    if not token:
        return None

    if any(request.path.startswith(prefix) for prefix in SKIP_PATH_PREFIXES):
        return None

    logger.info("URL token login: applying session cookie from query parameter")
    session_value = normalize_session_cookie_value(token)
    if session_value != token:
        logger.info("URL token login: prepended '.' to match Flask session cookie format")
    response = redirect(build_url_without_token())
    set_session_cookie(response, session_value)
    return response


def register_url_token_login(app: Flask) -> None:
    @app.before_request
    def url_token_login_before_request() -> Response | None:
        return handle_url_token_login()
