# JWT → Session Auto-Login Bridge

**Date:** 2026-07-23  
**Status:** Approved  
**Scope:** Alpha Superset — exchange FAB JWT for browser session cookie

## Problem

External systems can obtain a JWT via `POST /api/v1/security/login`, but the Alpha UI authenticates with a Flask **session cookie**. JWT alone does not log the user into the SPA. We need a bridge so an external frontend can establish a session and then navigate into Alpha already logged in.

## Goals

- External backend calls `/api/v1/security/login` and returns `access_token` to its frontend.
- External frontend calls a new Alpha endpoint with `Authorization: Bearer <access_token>` and `credentials: 'include'`.
- Alpha validates JWT, creates a Flask-Login session (`Set-Cookie`), returns a safe redirect path.
- Frontend navigates to that path and uses Alpha normally (session-based).

## Non-goals

- Changing `/api/v1/security/login` behavior.
- Replacing form login or existing URL `?token=` session-cookie login (`url_token_login`).
- Embedding-only guest tokens.

## Flow

```
External backend                 External frontend                    Alpha
       |                                |                               |
       | POST /api/v1/security/login ---------------------------------->|
       | {username, password, provider, refresh}                        |
       |<-- {access_token, refresh_token} ------------------------------|
       |-- access_token --------------->|                               |
       |                                | POST /api/v1/security/session |
       |                                | Authorization: Bearer <jwt>   |
       |                                | credentials: include -------->|
       |                                |                               | verify JWT
       |                                |                               | load user
       |                                |                               | login_user()
       |                                |<-- 200 {redirect} + Set-Cookie|
       |                                | location = redirect --------->|
       |                                |                         logged-in SPA
```

## API Design

### `POST /api/v1/security/session`

| Item | Value |
|------|--------|
| Auth | JWT Bearer (`access_token` from `/security/login`) |
| CSRF | Exempt (JWT clients do not carry CSRF cookies) |
| `allow_browser_login` | `False` for this method (JWT only) |
| Success | `200` + JSON `{ "redirect": "<path>" }` and session `Set-Cookie` |
| Errors | `401` invalid/expired/missing JWT; `404` user not found; `400` unsafe redirect |

#### Request

- Header: `Authorization: Bearer <access_token>` (required)
- Optional JSON body or query:
  - `redirect` (string): same-origin **relative** path only (e.g. `/alpha/welcome/`). Reject absolute URLs and `//` open redirects.

#### Response `200`

```json
{
  "redirect": "/alpha/welcome/"
}
```

Default redirect from config (see below) when `redirect` omitted.

#### Behavior

1. Require and verify JWT via flask-jwt-extended (`verify_jwt_in_request` / `@jwt_required`).
2. Resolve identity → load FAB user; reject inactive/anonymous.
3. `flask_login.login_user(user, remember=False)` so subsequent SPA requests use the session cookie.
4. Return redirect path; do not put JWT in the redirect URL.

## Configuration

| Key | Default | Purpose |
|-----|---------|---------|
| `JWT_SESSION_LOGIN_REDIRECT` | `URL_TOKEN_LOGIN_REDIRECT` / `LOGO_TARGET_PATH` / `/alpha/welcome/` | Default redirect after session bridge |
| CORS (ops) | Off by default | For cross-origin external frontends: enable CORS with credentials; set `SESSION_COOKIE_SAMESITE=None` and `SESSION_COOKIE_SECURE=True` under HTTPS |

## External frontend example

```javascript
const { access_token } = await yourBackendLogin(); // backend called /api/v1/security/login

const res = await fetch('https://bi.example/api/v1/security/session', {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${access_token}`,
    'Content-Type': 'application/json',
  },
  credentials: 'include',
  body: JSON.stringify({ redirect: '/alpha/welcome/' }),
});

if (!res.ok) throw new Error('session bridge failed');
const { redirect } = await res.json();
window.location.href = new URL(redirect, 'https://bi.example').toString();
```

## Implementation plan (repo)

1. Add endpoint on `SecurityRestApi` in `superset/security/api.py` (or thin helper module).
2. Safe redirect helper (relative path only).
3. Config key `JWT_SESSION_LOGIN_REDIRECT` in `superset/config.py`.
4. Unit/integration tests: valid JWT → session cookie; invalid JWT → 401; bad redirect → 400.
5. Short usage note in design doc / comment near the endpoint (no large new docs site unless requested).

## Security notes

- Prefer Bearer header over putting JWT in query strings.
- Validate redirect to prevent open redirects.
- Session cookie flags must match deployment (Secure / SameSite) for cross-site auto-login.
- Do not log full tokens.

## Out of scope follow-ups

- Refresh-token rotation on the bridge.
- Automatic user provisioning on first JWT login.
