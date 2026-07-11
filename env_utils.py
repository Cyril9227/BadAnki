# env_utils.py
# Environment-variable hygiene shared by modules that read config at import
# time. Lives in a leaf module so both main and the modules main imports
# (e.g. key_encryption) use the same cleaning — previously two copies had
# already started to drift.

import os


def clean_env_value(name: str):
    """The env value with whitespace and accidental wrapping quotes removed;
    None when unset or effectively empty."""
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value or None
