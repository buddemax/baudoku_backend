from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi.testclient import TestClient

from baudoku_api.dependencies import get_auth_service, get_project_repository
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.main import create_app
from baudoku_api.repositories import ProjectNotFoundError
from baudoku_api.schemas import ProjectCreate, ProjectUpdate

USER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_USER_ID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc).isoformat()


class FakeAuthService:
    def __init__(self, user_id: str = USER_ID) -> None:
        self.user = AuthenticatedUser(
            id=user_id,
            email="gutachter@example.com",
            display_name="Gutachter",
        )
        self.tokens: list[str] = []

    def authenticate(self, access_token: str) -> AuthenticatedUser:
        self.tokens.append(access_token)
        return self.user


class FakeProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[str, dict[str, Any]] = {}
        self.memberships: list[dict[str, str]] = []
        self.profiles: dict[str, dict[str, Any]] = {
            USER_ID: {
                "id": USER_ID,
                "display_name": "Gutachter",
                "email": "gutachter@example.com",
                "is_active": True,
            },
            OTHER_USER_ID: {
                "id": OTHER_USER_ID,
                "display_name": "Zweitnutzer",
                "email": "zweiter@example.com",
                "is_active": True,
            },
        }
        self.trades: list[dict[str, Any]] = [
            {
                "id": "33333333-3333-4333-8333-333333333333",
                "name": "Dach",
                "is_active": True,
            },
            {
                "id": "44444444-4444-4444-8444-444444444444",
                "name": "Fenster",
                "is_active": True,
            },
        ]

    def ensure_profile(self, auth_user: AuthenticatedUser) -> AuthenticatedUser:
        return auth_user

    def list_projects(
        self,
        user_id: str,
        search: Optional[str] = None,
        status: Optional[str] = None,
        appraisal_type: Optional[str] = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        visible_project_ids = {
            membership["project_id"]
            for membership in self.memberships
            if membership["user_id"] == user_id
        }
        visible_projects = [
            project
            for project_id, project in self.projects.items()
            if project_id in visible_project_ids
            and (include_deleted or project.get("deleted_at") is None)
        ]
        if search:
            normalized_search = search.casefold()
            visible_projects = [
                project
                for project in visible_projects
                if any(
                    normalized_search in str(project.get(field) or "").casefold()
                    for field in (
                        "project_number",
                        "client_name",
                        "object_address",
                        "site_visit_date",
                        "appraisal_type",
                        "status",
                    )
                )
            ]
        if status:
            visible_projects = [
                project for project in visible_projects if project.get("status") == status
            ]
        if appraisal_type:
            visible_projects = [
                project
                for project in visible_projects
                if project.get("appraisal_type") == appraisal_type
            ]
        return sorted(visible_projects, key=lambda project: project["updated_at"], reverse=True)

    def list_profiles(self, user_id: str) -> list[dict[str, Any]]:
        if user_id not in self.profiles:
            raise ProjectNotFoundError("Nutzerprofil nicht gefunden.")
        return sorted(self.profiles.values(), key=lambda profile: profile["display_name"])

    def list_trades(self, user_id: str) -> list[dict[str, Any]]:
        if user_id not in self.profiles:
            raise ProjectNotFoundError("Nutzerprofil nicht gefunden.")
        return sorted(self.trades, key=lambda trade: trade["name"])

    def create_project(self, payload: ProjectCreate, user: AuthenticatedUser) -> dict[str, Any]:
        project_id = str(uuid4())
        project = {
            "id": project_id,
            "project_number": payload.project_number,
            "client_name": payload.client_name,
            "object_address": payload.object_address,
            "site_visit_date": payload.site_visit_date.isoformat(),
            "appraisal_type": payload.appraisal_type,
            "lead_user_id": str(payload.lead_user_id or user.id),
            "status": "Entwurf",
            "language": payload.language,
            "created_by": user.id,
            "created_at": NOW,
            "updated_at": NOW,
            "deleted_at": None,
            "revision": 1,
        }
        self.projects[project_id] = project
        self.memberships.append({"project_id": project_id, "user_id": user.id})
        return project

    def get_project(self, project_id: str, user_id: str) -> dict[str, Any]:
        if {"project_id": project_id, "user_id": user_id} not in self.memberships:
            raise ProjectNotFoundError("Projekt nicht gefunden.")
        project = self.projects.get(project_id)
        if project is None or project.get("deleted_at") is not None:
            raise ProjectNotFoundError("Projekt nicht gefunden.")
        return project

    def update_project(
        self, project_id: str, payload: ProjectUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        project = self.get_project(project_id, user.id).copy()
        updates = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        project.update(updates)
        project["revision"] += 1
        project["updated_at"] = datetime(2026, 5, 4, 9, 0, tzinfo=timezone.utc).isoformat()
        self.projects[project_id] = project
        return project

    def delete_project(self, project_id: str, user: AuthenticatedUser) -> None:
        project = self.get_project(project_id, user.id).copy()
        project["deleted_at"] = datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc).isoformat()
        project["updated_at"] = datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc).isoformat()
        project["revision"] += 1
        self.projects[project_id] = project

    def seed_project(self, user_id: str = USER_ID, updated_at: str = NOW) -> str:
        project_id = str(uuid4())
        self.projects[project_id] = {
            "id": project_id,
            "project_number": "BBA-2026-001",
            "client_name": "Muster GmbH",
            "object_address": "Baustelle 1, Berlin",
            "site_visit_date": date(2026, 5, 4).isoformat(),
            "appraisal_type": "Abnahmebegehung",
            "lead_user_id": user_id,
            "status": "Entwurf",
            "language": "de",
            "created_by": user_id,
            "created_at": NOW,
            "updated_at": updated_at,
            "deleted_at": None,
            "revision": 1,
        }
        self.memberships.append({"project_id": project_id, "user_id": user_id})
        return project_id


def test_project_list_without_token_returns_401() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/projects")

    assert response.status_code == 401
    assert response.json()["detail"] == "Bearer Token fehlt."


def test_create_project_with_fake_auth_creates_project_and_membership() -> None:
    repository = FakeProjectRepository()
    auth_service = FakeAuthService()
    client = _client(repository, auth_service)

    response = client.post(
        "/v1/projects",
        headers={"Authorization": "Bearer fake-token"},
        json={
            "project_number": "BBA-2026-123",
            "client_name": "Bauherr AG",
            "object_address": "Musterstrasse 1, Hamburg",
            "site_visit_date": "2026-05-04",
            "appraisal_type": "Abnahmebegehung",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["project_number"] == "BBA-2026-123"
    assert data["status"] == "Entwurf"
    assert auth_service.tokens == ["fake-token"]
    assert repository.memberships == [{"project_id": data["id"], "user_id": USER_ID}]


def test_project_list_returns_member_projects_only() -> None:
    repository = FakeProjectRepository()
    visible_project_id = repository.seed_project(USER_ID, "2026-05-04T09:00:00+00:00")
    hidden_project_id = repository.seed_project(OTHER_USER_ID, "2026-05-04T10:00:00+00:00")
    client = _client(repository, FakeAuthService(USER_ID))

    response = client.get("/v1/projects", headers={"Authorization": "Bearer fake-token"})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [visible_project_id]
    assert hidden_project_id not in [item["id"] for item in response.json()["items"]]


def test_project_list_filters_by_search_status_and_type() -> None:
    repository = FakeProjectRepository()
    matching_id = repository.seed_project(USER_ID, "2026-05-04T09:00:00+00:00")
    other_id = repository.seed_project(USER_ID, "2026-05-04T10:00:00+00:00")
    repository.projects[other_id]["project_number"] = "BBA-2026-999"
    repository.projects[other_id]["client_name"] = "Andere AG"
    repository.projects[other_id]["status"] = "In Erfassung"
    repository.projects[other_id]["appraisal_type"] = "Schadensaufnahme"
    client = _client(repository, FakeAuthService(USER_ID))

    response = client.get(
        "/v1/projects?search=muster&status=Entwurf&appraisal_type=Abnahmebegehung",
        headers={"Authorization": "Bearer fake-token"},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [matching_id]


def test_get_and_patch_project() -> None:
    repository = FakeProjectRepository()
    project_id = repository.seed_project(USER_ID)
    client = _client(repository, FakeAuthService(USER_ID))

    get_response = client.get(
        f"/v1/projects/{project_id}",
        headers={"Authorization": "Bearer fake-token"},
    )
    patch_response = client.patch(
        f"/v1/projects/{project_id}",
        headers={"Authorization": "Bearer fake-token"},
        json={"status": "In Erfassung", "client_name": "Neue Bauherr AG"},
    )

    assert get_response.status_code == 200
    assert patch_response.status_code == 200
    assert patch_response.json()["status"] == "Entwurf"
    assert patch_response.json()["client_name"] == "Neue Bauherr AG"
    assert patch_response.json()["revision"] == 2


def test_delete_project_soft_deletes_project() -> None:
    repository = FakeProjectRepository()
    project_id = repository.seed_project(USER_ID)
    client = _client(repository, FakeAuthService(USER_ID))

    delete_response = client.delete(
        f"/v1/projects/{project_id}",
        headers={"Authorization": "Bearer fake-token"},
    )
    list_response = client.get("/v1/projects", headers={"Authorization": "Bearer fake-token"})

    assert delete_response.status_code == 204
    assert repository.projects[project_id]["deleted_at"] is not None
    assert list_response.json()["items"] == []


def test_project_list_can_include_deleted_projects() -> None:
    repository = FakeProjectRepository()
    project_id = repository.seed_project(USER_ID)
    client = _client(repository, FakeAuthService(USER_ID))

    client.delete(f"/v1/projects/{project_id}", headers={"Authorization": "Bearer fake-token"})
    list_response = client.get(
        "/v1/projects?include_deleted=true",
        headers={"Authorization": "Bearer fake-token"},
    )

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["id"] == project_id
    assert list_response.json()["items"][0]["deleted_at"] is not None


def test_reference_profiles_and_trades() -> None:
    repository = FakeProjectRepository()
    client = _client(repository, FakeAuthService(USER_ID))

    profiles_response = client.get("/v1/profiles", headers={"Authorization": "Bearer fake-token"})
    trades_response = client.get("/v1/trades", headers={"Authorization": "Bearer fake-token"})

    assert profiles_response.status_code == 200
    assert [item["display_name"] for item in profiles_response.json()["items"]] == [
        "Gutachter",
        "Zweitnutzer",
    ]
    assert trades_response.status_code == 200
    assert [item["name"] for item in trades_response.json()["items"]] == ["Dach", "Fenster"]


def _client(repository: FakeProjectRepository, auth_service: FakeAuthService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_project_repository] = lambda: repository
    return TestClient(app)
