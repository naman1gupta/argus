from datetime import datetime

from django.utils import timezone
from ninja import Router, Schema

from apps.accounts.security import admin_auth
from apps.projects.models import Project

router = Router(tags=["projects"], auth=admin_auth)


class ProjectOut(Schema):
    id: str
    name: str
    environment: str
    key_hint: str
    key_rotated_at: datetime
    created_at: datetime


class ProjectIn(Schema):
    name: str
    environment: str = "production"


class ProjectCreatedOut(ProjectOut):
    ingestion_key: str  # returned exactly once


@router.get("", response=list[ProjectOut])
def list_projects(request):
    return Project.objects.all()


@router.post("", response={201: ProjectCreatedOut})
def create_project(request, payload: ProjectIn):
    project = Project(name=payload.name, environment=payload.environment, created_by=request.auth)
    raw_key = project.issue_key()
    project.save()
    return 201, ProjectCreatedOut(ingestion_key=raw_key, **ProjectOut.from_orm(project).dict())


@router.post("/{project_id}/rotate-key", response=ProjectCreatedOut)
def rotate_key(request, project_id: str):
    project = Project.objects.get(pk=project_id)
    raw_key = project.issue_key()
    project.key_rotated_at = timezone.now()
    project.save()
    return ProjectCreatedOut(ingestion_key=raw_key, **ProjectOut.from_orm(project).dict())
