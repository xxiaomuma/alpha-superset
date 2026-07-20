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
"""Localized wrappers around the humanize library."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import humanize
from flask_babel import get_locale

logger = logging.getLogger(__name__)

# Map Flask-Babel locale codes to humanize locale codes
_HUMANIZE_LOCALE_MAP = {
    "zh": "zh_CN",
    "zh_CN": "zh_CN",
    "zh_TW": "zh_TW",
    "pt_BR": "pt_BR",
    "ja": "ja_JP",
    "ko": "ko_KR",
    "de": "de_DE",
    "fr": "fr_FR",
    "ru": "ru_RU",
    "nl": "nl_NL",
    "sk": "sk_SK",
    "tr": "tr_TR",
    "it": "it_IT",
    "es": "es_ES",
    "pt": "pt_PT",
    "uk": "uk_UA",
    "sl": "sl_SI",
}


def activate_humanize_for_locale(locale: str | None = None) -> None:
    """Activate humanize translations for the current (or given) locale."""
    if locale is None:
        babel_locale = get_locale()
        if babel_locale:
            locale = str(babel_locale)
        else:
            # Fall back to app default (e.g. zh) when request locale is unset
            try:
                from flask import current_app

                locale = current_app.config.get("BABEL_DEFAULT_LOCALE", "en")
            except Exception:  # pylint: disable=broad-except
                locale = "en"

    humanize_locale = _HUMANIZE_LOCALE_MAP.get(locale, locale)
    if humanize_locale in ("en", "en_US"):
        humanize.i18n.deactivate()
        return

    try:
        humanize.i18n.activate(humanize_locale)
    except Exception:  # pylint: disable=broad-except
        # Fallback: try language part only, then English
        lang = humanize_locale.split("_", maxsplit=1)[0]
        try:
            if lang == "zh":
                humanize.i18n.activate("zh_CN")
            else:
                humanize.i18n.deactivate()
        except Exception:  # pylint: disable=broad-except
            logger.debug("humanize locale %s unavailable", humanize_locale)
            humanize.i18n.deactivate()


def localized_naturaltime(value: timedelta | Any) -> str:
    """Return a locale-aware naturaltime string (e.g. '12 分钟前')."""
    activate_humanize_for_locale()
    return humanize.naturaltime(value)
