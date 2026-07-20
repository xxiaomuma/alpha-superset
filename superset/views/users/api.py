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

from flask import g, redirect, request, Response
from flask_appbuilder.api import expose, permission_name, protect, safe
from flask_jwt_extended.exceptions import NoAuthorizationError
from marshmallow import ValidationError
from sqlalchemy.orm.exc import NoResultFound

from superset import app, is_feature_enabled
from superset.commands.user.create import CreateUserCommand
from superset.commands.user.exceptions import (
    UserCreateFailedError,
    UserInvalidError,
)
from superset.daos.user import UserDAO
from superset.extensions import event_logger
from superset.utils.slack import get_user_avatar, SlackClientError
from superset.views.base_api import BaseSupersetApi, requires_json, statsd_metrics
from superset.views.users.schemas import UserCreateSchema, UserResponseSchema
from superset.views.utils import bootstrap_user_data

logger = logging.getLogger(__name__)
user_response_schema = UserResponseSchema()
user_create_schema = UserCreateSchema()


class CurrentUserRestApi(BaseSupersetApi):
    """An API to get information about the current user"""

    resource_name = "me"
    openapi_spec_tag = "Current User"
    openapi_spec_component_schemas = (UserResponseSchema,)

    @expose("/", methods=("GET",))
    @safe
    def get_me(self) -> Response:
        """Get the user object corresponding to the agent making the request.
        ---
        get:
          summary: Get the user object
          description: >-
            Gets the user object corresponding to the agent making the request,
            or returns a 401 error if the user is unauthenticated.
          responses:
            200:
              description: The current user
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        $ref: '#/components/schemas/UserResponseSchema'
            401:
              $ref: '#/components/responses/401'
        """
        try:
            if g.user is None or g.user.is_anonymous:
                return self.response_401()
        except NoAuthorizationError:
            return self.response_401()

        return self.response(200, result=user_response_schema.dump(g.user))

    @expose("/roles/", methods=("GET",))
    @safe
    def get_my_roles(self) -> Response:
        """Get the user roles corresponding to the agent making the request.
        ---
        get:
          summary: Get the user roles
          description: >-
            Gets the user roles corresponding to the agent making the request,
            or returns a 401 error if the user is unauthenticated.
          responses:
            200:
              description: The current user
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      result:
                        $ref: '#/components/schemas/UserResponseSchema'
            401:
              $ref: '#/components/responses/401'
        """
        try:
            if g.user is None or g.user.is_anonymous:
                return self.response_401()
        except NoAuthorizationError:
            return self.response_401()
        user = bootstrap_user_data(g.user, include_perms=True)
        return self.response(200, result=user)


class AddUserRestApi(BaseSupersetApi):
    """Create users via JWT-authenticated API (aligned with /users/add)."""

    resource_name = "add"
    # JWT only — browser session cookie is not accepted
    allow_browser_login = False
    # JWT clients do not send CSRF cookies/tokens
    csrf_exempt = True
    class_permission_name = "UserDBModelView"
    openapi_spec_tag = "User"
    openapi_spec_component_schemas = (UserResponseSchema, UserCreateSchema)

    @expose("/user", methods=("POST",))
    @protect()
    @safe
    @statsd_metrics
    @permission_name("add")
    @event_logger.log_this_with_context(
        action=lambda self, *args, **kwargs: f"{self.__class__.__name__}.post",
        log_to_statsd=False,
    )
    @requires_json
    def post(self) -> Response:
        """Create a new user.
        ---
        post:
          summary: Create a user
          description: >-
            Create a new user. Requires JWT Bearer token.
            Body fields align with the /users/add form.
          requestBody:
            required: true
            content:
              application/json:
                schema:
                  $ref: '#/components/schemas/UserCreateSchema'
          responses:
            201:
              description: User created
              content:
                application/json:
                  schema:
                    type: object
                    properties:
                      id:
                        type: integer
                      result:
                        $ref: '#/components/schemas/UserResponseSchema'
            400:
              $ref: '#/components/responses/400'
            401:
              $ref: '#/components/responses/401'
            403:
              $ref: '#/components/responses/403'
            422:
              $ref: '#/components/responses/422'
            500:
              $ref: '#/components/responses/500'
        """
        try:
            item = user_create_schema.load(request.json)
        except ValidationError as error:
            return self.response_400(message=error.messages)

        item.pop("conf_password", None)

        try:
            user = CreateUserCommand(item).run()
            return self.response(
                201,
                id=user.id,
                result=user_response_schema.dump(user),
            )
        except UserInvalidError as ex:
            return self.response_422(message=ex.normalized_messages())
        except UserCreateFailedError as ex:
            logger.error("Error creating user %s: %s", item.get("username"), str(ex))
            return self.response_422(message=str(ex))


class UserRestApi(BaseSupersetApi):
    """An API to get information about users"""

    resource_name = "user"
    openapi_spec_tag = "User"
    openapi_spec_component_schemas = (UserResponseSchema,)

    @expose("/<int:user_id>/avatar.png", methods=("GET",))
    @safe
    def avatar(self, user_id: int) -> Response:
        """Get a redirect to the avatar's URL for the user with the given ID.
        ---
        get:
          summary: Get the user avatar
          description: >-
            Gets the avatar URL for the user with the given ID, or returns a 401 error
            if the user is unauthenticated.
          parameters:
            - in: path
              name: user_id
              required: true
              description: The ID of the user
              schema:
                type: string
          responses:
            301:
              description: A redirect to the user's avatar URL
            401:
              $ref: '#/components/responses/401'
            404:
              $ref: '#/components/responses/404'
        """
        avatar_url = None
        try:
            user = UserDAO.get_by_id(user_id)
        except NoResultFound:
            return self.response_404()

        if not user:
            return self.response_404()

        # fetch from the one-to-one relationship
        if len(user.extra_attributes) > 0:
            avatar_url = user.extra_attributes[0].avatar_url
        slack_token = app.config.get("SLACK_API_TOKEN")
        if (
            not avatar_url
            and slack_token
            and is_feature_enabled("SLACK_ENABLE_AVATARS")
        ):
            try:
                # Fetching the avatar url from slack
                avatar_url = get_user_avatar(user.email)
            except SlackClientError:
                return self.response_404()

            UserDAO.set_avatar_url(user, avatar_url)

        # Return a permanent redirect to the avatar URL
        if avatar_url:
            return redirect(avatar_url, code=301)

        # No avatar found, return a "no-content" response
        return Response(status=204)
