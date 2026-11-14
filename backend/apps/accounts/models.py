import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **fields):
        fields.setdefault("is_staff", False)
        fields.setdefault("is_superuser", False)
        return self._create(email, password, **fields)

    def create_superuser(self, email, password=None, **fields):
        """A platform admin: not a member of any studio."""
        fields.update(is_staff=True, is_superuser=True, studio=None, role="")
        return self._create(email, password, **fields)


class User(AbstractBaseUser, PermissionsMixin):
    """A studio owner or staff member, or a platform admin (is_staff, no studio).

    Clients are not users; they get event-scoped access in Sprint 3.
    """

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        STAFF = "staff", "Staff"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    studio = models.ForeignKey(
        "studios.Studio", null=True, blank=True, on_delete=models.CASCADE, related_name="members"
    )
    role = models.CharField(max_length=10, choices=Role.choices, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Platform admin: can use Django admin.")
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["full_name"]
        constraints = [
            models.CheckConstraint(
                name="studio_member_has_role",
                condition=models.Q(studio__isnull=True, role="")
                | models.Q(studio__isnull=False, role__in=["owner", "staff"]),
            )
        ]

    def __str__(self) -> str:
        return f"{self.full_name} <{self.email}>"

    @property
    def is_owner(self) -> bool:
        return self.role == self.Role.OWNER

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None
