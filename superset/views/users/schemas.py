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
from marshmallow import fields, Schema, validate, validates_schema, ValidationError


class UserResponseSchema(Schema):
    id = fields.Integer()
    username = fields.String()
    email = fields.String()
    first_name = fields.String()
    last_name = fields.String()
    is_active = fields.Boolean()
    is_anonymous = fields.Boolean()


class UserCreateSchema(Schema):
    """Request body for creating a user (aligned with /users/add)."""

    username = fields.String(required=True, metadata={"description": "Username"})
    password = fields.String(required=True, metadata={"description": "Password"})
    conf_password = fields.String(
        required=True, metadata={"description": "Password confirmation"}
    )
    first_name = fields.String(
        load_default="",
        allow_none=True,
        metadata={"description": "First name (optional)"},
    )
    last_name = fields.String(
        load_default="",
        allow_none=True,
        metadata={"description": "Last name (optional)"},
    )
    email = fields.String(
        load_default="",
        allow_none=True,
        metadata={"description": "Email (optional)"},
    )
    active = fields.Boolean(
        load_default=True, metadata={"description": "Whether the user is active"}
    )
    roles = fields.List(
        fields.Integer(),
        required=True,
        metadata={"description": "List of role ids"},
    )

    @validates_schema
    def validate_passwords_match(self, data: dict, **kwargs: object) -> None:
        if data.get("password") != data.get("conf_password"):
            raise ValidationError(
                {"conf_password": ["Passwords do not match"]},
            )
        data["first_name"] = data.get("first_name") or ""
        data["last_name"] = data.get("last_name") or ""
        data["email"] = data.get("email") or ""
        if data["email"]:
            try:
                validate.Email()(data["email"])
            except ValidationError as ex:
                raise ValidationError({"email": list(ex.messages)}) from ex

