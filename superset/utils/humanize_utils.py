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
"""Localized relative-time helpers (thread-safe via Babel)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from babel.dates import format_timedelta
from flask_babel import get_locale

logger = logging.getLogger(__name__)

# Flask-Babel "zh" → Babel locale id
_BABEL_LOCALE_MAP = {
    "zh": "zh_CN",
    "zh_CN": "zh_CN",
    "zh_TW": "zh_TW",
}


def _resolve_locale(locale: str | None = None) -> str:
    if locale is None:
        babel_locale = get_locale()
        if babel_locale:
            locale = str(babel_locale)
        else:
            try:
                from flask import current_app

                locale = current_app.config.get("BABEL_DEFAULT_LOCALE", "en")
            except Exception:  # pylint: disable=broad-except
                locale = "en"
    return _BABEL_LOCALE_MAP.get(locale, locale)


def localized_naturaltime(value: timedelta | datetime | Any) -> str:
    """Return a locale-aware relative time string (e.g. '2分钟前').

    Callers typically pass ``now - past`` as a positive timedelta. Babel treats
    positive deltas as future ("后"), so we negate for past ("前" / "ago").
    """
    locale = _resolve_locale()

    if isinstance(value, datetime):
        delta = datetime.now(tz=value.tzinfo) - value
    elif isinstance(value, timedelta):
        delta = value
    else:
        delta = value

    try:
        # Positive (now - past) → negate so add_direction yields "ago" / "前"
        return format_timedelta(-delta, locale=locale, add_direction=True)
    except Exception:  # pylint: disable=broad-except
        logger.debug("format_timedelta failed for locale=%s", locale, exc_info=True)
        # Last resort: English humanize-style fallback without i18n deps
        try:
            import humanize

            humanize.i18n.deactivate()
            return humanize.naturaltime(delta)
        except Exception:  # pylint: disable=broad-except
            seconds = int(getattr(delta, "total_seconds", lambda: 0)())
            return f"{abs(seconds)} seconds ago"
