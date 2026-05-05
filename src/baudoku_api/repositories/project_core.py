from __future__ import annotations

from typing import Any, Optional

from baudoku_api.domain import AuthenticatedUser
from baudoku_api.schemas import ProjectCreate, ProjectUpdate

from baudoku_api.repositories.project_helpers import (
    ProjectNotFoundError,
    _filter_projects,
    _now_iso,
    _response_data,
    _single_response_row,
)


class ProjectCoreMixin:
    def ensure_profile(self, auth_user: AuthenticatedUser) -> AuthenticatedUser:
        existing = self._select_one("profiles", "id", auth_user.id)
        if existing is None:
            self._execute(
                self._client.table("profiles").insert(
                    {
                        "id": auth_user.id,
                        "email": auth_user.email,
                        "display_name": auth_user.display_name,
                        "is_active": False,
                    }
                )
            )
            return AuthenticatedUser(
                id=auth_user.id,
                email=auth_user.email,
                display_name=auth_user.display_name,
                is_active=False,
            )

        if not bool(existing.get("is_active", True)):
            return AuthenticatedUser(
                id=str(existing["id"]),
                email=str(existing.get("email") or auth_user.email),
                display_name=str(existing.get("display_name") or auth_user.display_name),
                is_active=False,
            )

        profile_updates: dict[str, Any] = {}
        if existing.get("email") != auth_user.email:
            profile_updates["email"] = auth_user.email
        if existing.get("display_name") != auth_user.display_name:
            profile_updates["display_name"] = auth_user.display_name

        if profile_updates:
            profile_updates["updated_at"] = _now_iso()
            self._execute(
                self._client.table("profiles").update(profile_updates).eq("id", auth_user.id)
            )

        return AuthenticatedUser(
            id=str(existing["id"]),
            email=str(profile_updates.get("email") or existing.get("email") or auth_user.email),
            display_name=str(
                profile_updates.get("display_name")
                or existing.get("display_name")
                or auth_user.display_name
            ),
        )

    def list_projects(
        self,
        user_id: str,
        search: Optional[str] = None,
        status: Optional[str] = None,
        appraisal_type: Optional[str] = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        response = self._execute(
            self._client.table("project_members")
            .select("projects(*)")
            .eq("user_id", user_id)
        )
        projects = [
            membership["projects"]
            for membership in _response_data(response)
            if membership.get("projects")
        ]
        if not include_deleted:
            projects = [project for project in projects if not project.get("deleted_at")]
        projects = [self._with_derived_project_status(project) for project in projects]
        projects = _filter_projects(projects, search, status, appraisal_type)
        return sorted(projects, key=lambda project: project.get("updated_at") or "", reverse=True)

    def list_profiles(self, user_id: str) -> list[dict[str, Any]]:
        profile = self._select_one("profiles", "id", user_id)
        if profile is None or not bool(profile.get("is_active", True)):
            raise ProjectNotFoundError("Nutzerprofil nicht gefunden.")
        response = self._execute(
            self._client.table("profiles")
            .select("id,display_name,email,is_active")
            .eq("is_active", True)
            .order("display_name")
        )
        return _response_data(response)

    def list_trades(self, user_id: str) -> list[dict[str, Any]]:
        profile = self._select_one("profiles", "id", user_id)
        if profile is None or not bool(profile.get("is_active", True)):
            raise ProjectNotFoundError("Nutzerprofil nicht gefunden.")
        response = self._execute(
            self._client.table("trades")
            .select("id,name,is_active")
            .eq("is_active", True)
            .order("name")
        )
        return _response_data(response)

    def create_project(self, payload: ProjectCreate, user: AuthenticatedUser) -> dict[str, Any]:
        project_payload = payload.model_dump(mode="json", exclude_none=True)
        project_payload["created_by"] = user.id
        project_payload["lead_user_id"] = str(payload.lead_user_id or user.id)
        project_payload["status"] = "Entwurf"

        created_project = _single_response_row(
            self._execute(self._client.table("projects").insert(project_payload))
        )
        project_id = str(created_project["id"])
        self._create_memberships(project_id, user.id)
        self._record_activity(project_id, user.id, "project.created", "project", project_id)
        return created_project

    def get_project(self, project_id: str, user_id: str) -> dict[str, Any]:
        return self._get_project_for_user(project_id, user_id, derive_status=True)

    def _get_project_for_user(
        self, project_id: str, user_id: str, derive_status: bool = False
    ) -> dict[str, Any]:
        response = self._execute(
            self._client.table("project_members")
            .select("projects(*)")
            .eq("project_id", project_id)
            .eq("user_id", user_id)
            .limit(1)
        )
        rows = _response_data(response)
        if not rows or not rows[0].get("projects") or rows[0]["projects"].get("deleted_at"):
            raise ProjectNotFoundError("Projekt nicht gefunden.")
        project = rows[0]["projects"]
        if derive_status:
            return self._with_derived_project_status(project)
        return project

    def update_project(
        self, project_id: str, payload: ProjectUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        current_project = self.get_project(project_id, user.id)
        update_payload = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        update_payload.pop("status", None)
        if not update_payload:
            return current_project

        update_payload["updated_at"] = _now_iso()
        update_payload["revision"] = int(current_project.get("revision") or 1) + 1

        updated_project = _single_response_row(
            self._execute(
                self._client.table("projects").update(update_payload).eq("id", project_id)
            )
        )
        self._record_activity(project_id, user.id, "project.updated", "project", project_id)
        return self._with_derived_project_status(updated_project)

    def delete_project(self, project_id: str, user: AuthenticatedUser) -> None:
        current_project = self.get_project(project_id, user.id)
        self._execute(
            self._client.table("projects")
            .update(
                {
                    "deleted_at": _now_iso(),
                    "updated_at": _now_iso(),
                    "revision": int(current_project.get("revision") or 1) + 1,
                }
            )
            .eq("id", project_id)
        )
        self._record_activity(project_id, user.id, "project.deleted", "project", project_id)
