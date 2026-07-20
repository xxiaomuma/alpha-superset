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
from functools import partial
from typing import Any

from flask_appbuilder.security.sqla.models import User
from flask_babel import lazy_gettext as _
from marshmallow import ValidationError

from superset.commands.base import BaseCommand
from superset.commands.user.exceptions import (
    UserCreateFailedError,
    UserEmailExistsValidationError,
    UserExistsValidationError,
    UserInvalidError,
)
from superset.commands.utils import populate_roles
from superset.extensions import db, security_manager
from superset.utils.decorators import on_error, transaction

logger = logging.getLogger(__name__)


class CreateUserCommand(BaseCommand):
    def __init__(self, data: dict[str, Any]):
        self._properties = data.copy()
        self._roles: list[Any] = []

    @transaction(on_error=partial(on_error, reraise=UserCreateFailedError))
    def run(self) -> User:
        self.validate()
        user = security_manager.add_user(
            username=self._properties["username"],
            first_name=self._properties.get("first_name") or "",
            last_name=self._properties.get("last_name") or "",
            email=self._properties.get("email") or "",
            role=self._roles,
            password=self._properties["password"],
        )
        if not user:
            raise UserCreateFailedError()

        user.active = self._properties.get("active", True)
        db.session.flush()
        return user

    def validate(self) -> None:
        exceptions: list[ValidationError] = []
        username = self._properties["username"]
        email = self._properties.get("email") or ""

        if security_manager.find_user(username=username):
            exceptions.append(UserExistsValidationError())

        if email and security_manager.find_user(email=email):
            exceptions.append(UserEmailExistsValidationError())

        try:
            self._roles = populate_roles(self._properties.get("roles") or [])
            if not self._roles:
                exceptions.append(
                    ValidationError(
                        [_("At least one role is required")],
                        field_name="roles",
                    )
                )
        except ValidationError as ex:
            exceptions.append(ex)

        if exceptions:
            raise UserInvalidError(exceptions=exceptions)
