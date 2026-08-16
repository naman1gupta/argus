from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin"
        MEMBER = "member"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN
