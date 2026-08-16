import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.projects.models import Project


class Command(BaseCommand):
    help = "Idempotently seeds demo users (admin/member) and the default project."

    def handle(self, *args, **options):
        User = get_user_model()
        admin_pw = os.environ.get("DEMO_ADMIN_PASSWORD", "argus-admin")
        member_pw = os.environ.get("DEMO_MEMBER_PASSWORD", "argus-member")

        if not User.objects.filter(username="admin").exists():
            User.objects.create_user(username="admin", password=admin_pw, role="admin")
            self.stdout.write("created user: admin (role=admin)")
        if not User.objects.filter(username="member").exists():
            User.objects.create_user(username="member", password=member_pw, role="member")
            self.stdout.write("created user: member (role=member)")

        if not Project.objects.exists():
            project = Project(name="default", environment="production")
            raw_key = project.issue_key()
            project.save()
            self.stdout.write("created project 'default' — ingestion key (shown once):")
            self.stdout.write(self.style.SUCCESS(raw_key))
        else:
            self.stdout.write("projects already exist, skipping")
