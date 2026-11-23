from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.core.validators import pincode, single_line, whatsapp_number

from .models import User


class StudioSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()


class MeSerializer(serializers.ModelSerializer):
    studio = StudioSummarySerializer(allow_null=True)
    email_verified = serializers.BooleanField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "role", "email_verified", "studio"]


class SignupSerializer(serializers.Serializer):
    studio_name = serializers.CharField(max_length=200, validators=[single_line])
    full_name = serializers.CharField(max_length=150, validators=[single_line])
    email = serializers.EmailField()
    phone = serializers.CharField(
        max_length=30, error_messages={"blank": "Enter your WhatsApp number."}
    )
    pincode = serializers.CharField(
        max_length=10, error_messages={"blank": "Enter your studio's PIN code."}
    )
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_phone(self, value):
        return whatsapp_number(value)

    def validate_pincode(self, value):
        return pincode(value)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        candidate = User(email=attrs["email"], full_name=attrs["full_name"])
        try:
            password_validation.validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            # Report under the password field so the form shows it next to that input.
            raise serializers.ValidationError({"password": exc.messages}) from exc
        if attrs["password_confirm"] != attrs["password"]:
            raise serializers.ValidationError({"password_confirm": ["The passwords do not match."]})
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField()


class PasswordSetSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)
    password_confirm = serializers.CharField(trim_whitespace=False)


class StaffSerializer(serializers.ModelSerializer):
    email_verified = serializers.BooleanField(read_only=True)
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "is_active",
            "email_verified",
            "has_password",
            "date_joined",
        ]
        read_only_fields = ["id", "role", "is_active", "email_verified", "date_joined"]

    def get_has_password(self, obj) -> bool:
        return obj.has_usable_password()


class StaffInviteSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, validators=[single_line])
    email = serializers.EmailField()

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
