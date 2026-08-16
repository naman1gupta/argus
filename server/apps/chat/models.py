from django.conf import settings
from django.db import models
from ulid import ULID


def new_ulid() -> str:
    return str(ULID())


class Session(models.Model):
    """A chat conversation. Its id doubles as the telemetry session/conversation
    id, so chat turns can be joined to inference logs without a FK across apps."""

    id = models.CharField(primary_key=True, max_length=26, default=new_ulid, editable=False)
    title = models.CharField(max_length=200, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="sessions"
    )
    project = models.ForeignKey(
        "projects.Project", null=True, on_delete=models.SET_NULL, related_name="sessions"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.id} ({self.title or 'untitled'})"


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"
        SYSTEM = "system"

    id = models.CharField(primary_key=True, max_length=26, default=new_ulid, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    # Set on assistant messages; joins a chat turn to its telemetry row.
    generation_id = models.CharField(max_length=26, null=True, blank=True)
    provider = models.CharField(max_length=32, blank=True, default="")
    model = models.CharField(max_length=100, blank=True, default="")
    seq = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["seq"]
        constraints = [
            models.UniqueConstraint(fields=["session", "seq"], name="uniq_message_seq_per_session"),
        ]
