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
"""Translate navbar menu labels when building bootstrap menu_data."""

from __future__ import annotations

from typing import Any

from flask_babel import gettext

from superset.translations.utils import get_language_pack

# FAB view name -> gettext msgid (label differs from internal name).
_MSGID_BY_VIEW_NAME: dict[str, str] = {
    "Databases": "Database Connections",
}

# Fallback when .mo / messages.json are missing in the image.
_BUILTIN_LABELS: dict[str, dict[str, str]] = {
    "zh": {
        "Database Connections": "数据库连接",
        "Databases": "数据库连接",
    },
    "zh_TW": {
        "Database Connections": "資料庫連接",
        "Databases": "資料庫連接",
    },
}


def _builtin_label(label: str, locale: str) -> str | None:
    for key in (locale, locale.split("_")[0], locale.split("-")[0]):
        if key and key in _BUILTIN_LABELS:
            if translated := _BUILTIN_LABELS[key].get(label):
                return translated
    return None


def translate_menu_label(label: str, locale: str, name: str | None = None) -> str:
    if name and name in _MSGID_BY_VIEW_NAME:
        label = _MSGID_BY_VIEW_NAME[name]
    if not label:
        return label

    label = str(label).strip()

    language_pack = get_language_pack(locale) or {}
    translations = language_pack.get("locale_data", {}).get("superset", {})
    if entries := translations.get(label):
        if entries and entries[0]:
            return entries[0]

    translated = gettext(label)
    if translated != label:
        return translated

    if builtin := _builtin_label(label, locale):
        return builtin

    return label


def localize_menu_item(item: Any, locale: str) -> Any:
    if isinstance(item, str):
        return item
    if not item:
        return item

    localized = dict(item)
    name = localized.get("name")
    if label := localized.get("label"):
        localized["label"] = translate_menu_label(str(label), locale, str(name or ""))
    elif name:
        localized["label"] = translate_menu_label("", locale, str(name))
    if childs := localized.get("childs"):
        localized["childs"] = [localize_menu_item(child, locale) for child in childs]
    return localized


def localize_menu(menu: list[Any], locale: str) -> list[Any]:
    return [localize_menu_item(item, locale) for item in menu if item]
