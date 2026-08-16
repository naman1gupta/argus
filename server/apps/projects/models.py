import hashlib
import secrets

from django.conf import settings
from django.db import models

from apps.chat.models import new_ulid

KEY_PREFIX = "argus_sk_"


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


class Project(models.Model):
    id = models.CharField(primary_key=True, max_length=26, default=new_ulid, editable=False)
    name = models.CharField(max_length=100, unique=True)
    environment = models.CharField(max_length=40, default="production")
    key_hash = models.CharField(max_length=64, unique=True)
    key_hint = models.CharField(max_length=20)  # first/last chars for display
    key_rotated_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="projects"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def issue_key(self) -> str:
        """Generates a new ingestion key; only the hash is stored. Returns the raw key once."""
        raw = KEY_PREFIX + secrets.token_urlsafe(32)
        self.key_hash = hash_key(raw)
        self.key_hint = f"{raw[:12]}…{raw[-4:]}"
        return raw

    @classmethod
    def authenticate_key(cls, raw_key: str) -> "Project | None":
        if not raw_key or not raw_key.startswith(KEY_PREFIX):
            return None
        return cls.objects.filter(key_hash=hash_key(raw_key)).first()

    def __str__(self) -> str:
        return self.name
