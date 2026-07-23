# JWT → Session Auto-Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/v1/security/session` that exchanges a FAB JWT for a Flask session cookie.

**Architecture:** Endpoint on `SecurityRestApi` (or dedicated JWT-only API class). Verify Bearer JWT → load user → `login_user()` → return `{redirect}`.

**Tech Stack:** Flask-AppBuilder, flask-jwt-extended, flask-login

**Spec:** `docs/superpowers/specs/2026-07-23-jwt-session-auto-login-design.md`

## File map

| File | Responsibility |
|------|----------------|
| `superset/config.py` | `JWT_SESSION_LOGIN_REDIRECT` |
| `superset/utils/jwt_session_login.py` | Safe redirect helper + resolve default redirect |
| `superset/security/api.py` | `POST /session` endpoint |
| `tests/unit_tests/security/test_jwt_session_login.py` | Unit tests for redirect helper + API |

## Task 1: Config + safe redirect helper

- [x] Add `JWT_SESSION_LOGIN_REDIRECT` to `superset/config.py`
- [x] Implement `superset/utils/jwt_session_login.py` with `is_safe_redirect_path` and `resolve_session_login_redirect`
- [x] Unit-test redirect validation

## Task 2: Session bridge endpoint

- [x] Add `POST /session` on security API: JWT required, `login_user`, return redirect
- [x] CSRF exempt / JWT-only as needed so external frontends can call it
- [x] Integration-style unit test with app client + access token

## Task 3: Verify

- [ ] Run unit tests for the new module/endpoint (local env lacks pytest deps)
