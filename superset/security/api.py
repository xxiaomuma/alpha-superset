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
import logging
from typing import Any

from flask import current_app, request, Response
from flask_appbuilder import expose
from flask_appbuilder.api import safe
from flask_appbuilder.security.decorators import permission_name, protect
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_login import login_user
from flask_wtf.csrf import generate_csrf
from marshmallow import EXCLUDE, fields, post_load, Schema, ValidationError

from superset.commands.dashboard.embedded.exceptions import (
    EmbeddedDashboardNotFoundError,
)
from superset.exceptions import SupersetGenericErrorException
from superset.extensions import event_logger
from superset.security.guest_token import GuestTokenResourceType
from superset.utils.jwt_session_login import (
    resolve_session_login_redirect,
    UnsafeRedirectError,
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

        identity = get_jwt_identity()
        security_manager = self.appbuilder.sm
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

        if user is None or getattr(user, "is_anonymous", False):
            return self.response_404()
        if hasattr(user, "active") and not user.active:
            return self.response_401()

        login_user(user, remember=False)

        requested = None
        if request.is_json and isinstance(request.json, dict):
            requested = request.json.get("redirect")
        if requested is None:
            requested = request.args.get("redirect")

        try:
            redirect_path = resolve_session_login_redirect(requested)
        except UnsafeRedirectError:
            return self.response_400(message="Invalid redirect path")

        return self.response(200, redirect=redirect_path)
