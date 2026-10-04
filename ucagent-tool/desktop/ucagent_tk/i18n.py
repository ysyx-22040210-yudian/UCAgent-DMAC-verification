"""Load packaged desktop display text without depending on backend installation paths."""

import json
from pkgutil import get_data

STRINGS = json.loads(get_data("ucagent_tk", "lang/zh.json").decode("utf-8"))


def tr(key, **values):
    """Translate a stable display key and substitute explicit named values."""
    text = STRINGS.get(key, key)
    return text.format(**values) if values else text
