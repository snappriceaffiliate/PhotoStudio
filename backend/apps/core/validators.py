"""Input checks shared by serializers."""

import unicodedata

from rest_framework import serializers

# Not allowed in uploaded paths: they are unsafe in the copy scripts or cannot exist in
# Windows file names, so a path containing them could never match a file on disk anyway.
PATH_FORBIDDEN = set('|*?"<>')


def has_control_chars(value: str) -> bool:
    return any(unicodedata.category(ch) == "Cc" for ch in value)


def single_line(value: str) -> str:
    """For names and titles: no line breaks or other control characters."""
    if has_control_chars(value):
        raise serializers.ValidationError("Use plain text on one line.")
    return value


def safe_relative_path(value: str) -> str:
    if has_control_chars(value) or PATH_FORBIDDEN & set(value):
        raise serializers.ValidationError(
            'File and folder names cannot contain line breaks or any of | * ? " < >.'
        )
    return value
