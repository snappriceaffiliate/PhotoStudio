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


def whatsapp_number(value: str) -> str:
    """A phone number as WhatsApp links need it: country code and number, digits only.

    Without a + (or 00) the number is read as an Indian mobile, typed any usual way
    (98765 43210, 098765 43210, 91 98765 43210). Other countries need their + code.
    """
    raw = value.strip().lstrip("( ")
    digits = "".join(ch for ch in raw if ch.isdigit())
    international = raw.startswith("+") or raw.startswith("00")
    if raw.startswith("00"):
        digits = digits[2:]
    if not international:
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if not (len(digits) == 10 and digits[0] in "6789"):
            raise serializers.ValidationError(
                "Enter a 10-digit Indian mobile number, or add the + country code for other countries."
            )
        return "91" + digits
    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        raise serializers.ValidationError(
            "Enter the number with its country code, for example +44 7700 900123."
        )
    return digits
