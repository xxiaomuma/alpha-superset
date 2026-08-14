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
import base64
import json
import logging
from typing import Any

from flask import current_app, redirect, request, Response
from flask_appbuilder import expose
from flask_appbuilder.api import safe
from flask_appbuilder.security.decorators import permission_name, protect
from flask_jwt_extended import decode_token, get_jwt, get_jwt_identity, verify_jwt_in_request
from flask_wtf.csrf import generate_csrf
from marshmallow import EXCLUDE, fields, post_load, Schema, ValidationError

from superset.commands.dashboard.embedded.exceptions import (
    EmbeddedDashboardNotFoundError,
)
from superset.exceptions import SupersetGenericErrorException
from superset.extensions import event_logger
from superset.security.guest_token import GuestTokenResourceType
from superset.utils.jwt_session_login import (
    establish_session_from_identity,
    resolve_session_login_redirect,
    SessionLoginError,
    UnauthorizedSessionLogin,
    UnsafeRedirectError,
    UserNotFoundSessionLogin,
)
from superset.views.base_api import BaseSupersetApi, statsd_metrics

logger = logging.getLogger(__name__)


class PermissiveSchema(Schema):
    """
    A marshmallow schema that ignores unexpected fields, instead of throwing an error.
    """

    class Meta:  # pylint: disable=too-few-public-methods
        unknown = EXCLUDE


class UserSchema(PermissiveSchema):
    username = fields.String()
    first_name = fields.String()
    last_name = fields.String()


class ResourceSchema(PermissiveSchema):
    type = fields.Enum(GuestTokenResourceType, by_value=True, required=True)
    id = fields.String(required=True)

    @post_load
    def convert_enum_to_value(  # pylint: disable=unused-argument
        self,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        # we don't care about the enum, we want the value inside
        data["type"] = data["type"].value
        return data


class RlsRuleSchema(PermissiveSchema):
    dataset = fields.Integer()
    clause = fields.String(required=True)  # todo other options?


class GuestTokenCreateSchema(PermissiveSchema):
    user = fields.Nested(UserSchema)
    resources = fields.List(fields.Nested(ResourceSchema), required=True)
    rls = fields.List(fields.Nested(RlsRuleSchema), required=True)


guest_token_create_schema = GuestTokenCreateSchema()


class SecurityRestApi(BaseSupersetApi):
    resource_name = "security"
    allow_browser_login = True
    # JWT clients (login → /session) do not send CSRF cookies/tokens
    csrf_exempt = True
    openapi_spec_tag = "Security"

    @expose("/csrf_token/", methods=("GET",))
    @event_logger.log_this
    @protect()
    @safe
    @statsd_metrics
    @permission_name("read")
    def csrf_token(self) -> Response:
        """Get the CSRF token.
        ---
        get:
          summary: Get the CSRF token
          responses:
            200:
              description: Result contains the CSRF token
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                        result:
                          type: string
            401:
              $ref: '#/components/responses/401'
            500:
              $ref: '#/components/responses/500'
        """
        return self.response(200, result=generate_csrf())

    @expose("/guest_token/", methods=("POST",))
    @event_logger.log_this
    @protect()
    @safe
    @statsd_metrics
    @permission_name("grant_guest_token")
    def guest_token(self) -> Response:
        """Get a guest token that can be used for auth in embedded Superset.
        ---
        post:
          summary: Get a guest token
          requestBody:
            description: Parameters for the guest token
            required: true
            content:
              application/json:
                schema: GuestTokenCreateSchema
          responses:
            200:
              description: Result contains the guest token
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                        token:
                          type: string
            401:
              $ref: '#/components/responses/401'
            400:
              $ref: '#/components/responses/400'
            500:
              $ref: '#/components/responses/500'
        """
        try:
            body = guest_token_create_schema.load(request.json)
            self.appbuilder.sm.validate_guest_token_resources(body["resources"])
            guest_token_validator_hook = current_app.config.get(
                "GUEST_TOKEN_VALIDATOR_HOOK"
            )
            # Run validator to ensure the token parameters are OK.
            if guest_token_validator_hook is not None:
                if callable(guest_token_validator_hook):
                    if not guest_token_validator_hook(body):
                        raise ValidationError(message="Guest token validation failed")
                else:
                    raise SupersetGenericErrorException(
                        message="Guest token validator hook not callable"
                    )
            # TODO: Add generic validation:
            # make sure username doesn't reference an existing user
            # check rls rules for validity?
            token = self.appbuilder.sm.create_guest_access_token(
                body["user"], body["resources"], body["rls"]
            )
            return self.response(200, token=token)
        except EmbeddedDashboardNotFoundError as error:
            return self.response_400(message=error.message)
        except ValidationError as error:
            return self.response_400(message=error.messages)

    @expose("/session", methods=("POST",))
    @event_logger.log_this
    @safe
    @statsd_metrics
    def create_session(self) -> Response:
        """Exchange a JWT access token for a Flask browser session cookie.
        ---
        post:
          summary: Create a browser session from JWT
          description: >-
            Validates the Bearer access_token from /api/v1/security/login,
            establishes a Flask-Login session (Set-Cookie), and returns a
            safe relative redirect path for the SPA.
            On plain HTTP cross-origin, prefer GET /session/redirect instead.
          parameters:
          - in: header
            name: Authorization
            required: true
            schema:
              type: string
            description: Bearer access_token
          requestBody:
            required: false
            content:
              application/json:
                schema:
                  type: object
                  properties:
                    redirect:
                      type: string
                      description: Same-origin relative path (e.g. /alpha/welcome/)
          responses:
            200:
              description: Session cookie set
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      redirect:
                        type: string
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            404:
              $ref: '#/components/responses/404'
        """
        try:
            verify_jwt_in_request()
        except Exception:  # pylint: disable=broad-except
            return self.response_401()

        try:
            header_rls = request.headers.get("X-RLS-Rules")
            if header_rls:
                rls_rules = json.loads(base64.urlsafe_b64decode(header_rls).decode("utf-8"))
            else:
                jwt_data = get_jwt()
                rls_rules = jwt_data.get("rls_rules")
            establish_session_from_identity(
                self.appbuilder.sm, get_jwt_identity(), rls_rules
            )
            requested = None
            if request.is_json and isinstance(request.json, dict):
                requested = request.json.get("redirect")
            if requested is None:
                requested = request.args.get("redirect")
            redirect_path = resolve_session_login_redirect(requested)
        except UnsafeRedirectError:
            return self.response_400(message="Invalid redirect path")
        except UserNotFoundSessionLogin:
            return self.response_404()
        except UnauthorizedSessionLogin:
            return self.response_401()
        except SessionLoginError as ex:
            return self.response_400(message=str(ex))

        return self.response(200, redirect=redirect_path)

    @expose("/session/redirect", methods=("GET",))
    @event_logger.log_this
    @safe
    @statsd_metrics
    def create_session_redirect(self) -> Response:
        """HTTP-friendly auto-login via top-level browser navigation.
        ---
        get:
          summary: Create session from JWT query token and redirect
          description: >-
            For plain HTTP / cross-origin portals: navigate the browser here
            with ?token=<access_token>. Sets a SameSite=Lax session cookie
            (works without HTTPS) then redirects into the app.
          parameters:
          - in: query
            name: token
            required: true
            schema:
              type: string
            description: access_token from /api/v1/security/login
          - in: query
            name: redirect
            required: false
            schema:
              type: string
            description: Relative path after login (default /alpha/welcome/)
          responses:
            302:
              description: Session cookie set; redirect to app
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            404:
              $ref: '#/components/responses/404'
        """
        token = (request.args.get("token") or "").strip()
        if not token:
            return self.response_401()

        try:
            decoded = decode_token(token)
            identity = decoded.get("sub")
            rls_rules_param = request.args.get("rls_rules")
            if rls_rules_param:
                rls_rules = json.loads(base64.urlsafe_b64decode(rls_rules_param).decode("utf-8"))
            else:
                rls_rules = decoded.get("rls_rules")
            # #region agent log
            with open("debug-7d8189.log", "a") as f:
                import datetime
                f.write(f'{{"sessionId":"7d8189","id":"log_{datetime.datetime.now().timestamp()}","timestamp":{int(datetime.datetime.now().timestamp()*1000)},"location":"api.py:318","message":"Session redirect success","data":{{"identity":identity,"rls_rules":rls_rules}},"runId":"debug","hypothesisId":"A"}}\\n')
            # #endregion
            establish_session_from_identity(self.appbuilder.sm, identity, rls_rules)
            redirect_path = resolve_session_login_redirect(
                request.args.get("redirect")
            )
        except UnsafeRedirectError:
            return self.response_400(message="Invalid redirect path")
        except UserNotFoundSessionLogin:
            return self.response_404()
        except UnauthorizedSessionLogin:
            return self.response_401()
        except Exception as e:  # pylint: disable=broad-except
            # #region agent log
            with open("debug-7d8189.log", "a") as f:
                import datetime
                f.write(f'{{"sessionId":"7d8189","id":"log_{datetime.datetime.now().timestamp()}","timestamp":{int(datetime.datetime.now().timestamp()*1000)},"location":"api.py:335","message":"JWT session redirect failed","data":{{"error_type":"{type(e).__name__}","error":str(e)}},"runId":"debug","hypothesisId":"A"}}\\n')
            # #endregion
            logger.exception("JWT session redirect login failed")
            return self.response_401()

        return redirect(redirect_path)
