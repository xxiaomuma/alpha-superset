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
"""Translate FAB permission names for display via Flask-Babel / messages.po."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask_appbuilder.security.sqla.models import Permission, PermissionView, ViewMenu

_INSTALLED = False


def translate_permission_name(name: str) -> str:
    """Return a localized label for an ab_permission.name value."""
    from flask_babel import gettext

    return gettext(name)


def translate_view_menu_name(name: str) -> str:
    """Return a localized label for an ab_view_menu.name value."""
    from flask_babel import gettext

    return gettext(name)


def _permission_str(self: Permission) -> str:
    return translate_permission_name(self.name)


def _view_menu_str(self: ViewMenu) -> str:
    return translate_view_menu_name(self.name)


def _permission_view_str(self: PermissionView) -> str:
    if self.permission and self.view_menu:
        return (
            f"{translate_permission_name(self.permission.name)}"
            f" on {translate_view_menu_name(self.view_menu.name)}"
        )
    return repr(self)


def install_fab_permission_label_translation() -> None:
    """Patch FAB SQLA models so security UIs use gettext labels."""
    global _INSTALLED  # pylint: disable=global-statement
    if _INSTALLED:
        return

    from flask_appbuilder.security.sqla.models import (
        Permission,
        PermissionView,
        ViewMenu,
    )

    Permission.__str__ = _permission_str  # type: ignore[method-assign,assignment]
    Permission.__repr__ = _permission_str  # type: ignore[method-assign,assignment]
    ViewMenu.__str__ = _view_menu_str  # type: ignore[method-assign,assignment]
    ViewMenu.__repr__ = _view_menu_str  # type: ignore[method-assign,assignment]
    PermissionView.__str__ = _permission_view_str  # type: ignore[method-assign,assignment]
    PermissionView.__repr__ = _permission_view_str  # type: ignore[method-assign,assignment]
    _INSTALLED = True
