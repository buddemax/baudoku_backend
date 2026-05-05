from pathlib import Path

import pytest

from baudoku_api.domain import AuthenticatedUser
from baudoku_api.repositories.projects import SupabaseProjectRepository


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"
SUPABASE_CONFIG = ROOT / "supabase" / "config.toml"


@pytest.mark.skipif(
    not MIGRATIONS_DIR.exists(),
    reason="Supabase migrations are outside standalone backend checkouts.",
)
def test_final_rls_policies_block_membership_escalation_and_inactive_users() -> None:
    policies = _final_policy_definitions()

    assert ("project_members", "active users can create memberships") not in policies
    assert ("project_members", "members can read memberships") in policies
    assert "user_id = (select auth.uid())" in policies[
        ("project_members", "members can read memberships")
    ]
    assert "private.current_user_is_active()" in policies[
        ("project_members", "members can read memberships")
    ]

    protected_policy_names = [
        ("projects", "members can update projects"),
        ("defects", "members can manage defects"),
        ("media_assets", "members can manage media"),
        ("defect_media_links", "members can manage defect media links"),
        ("voice_notes", "members can manage voice notes"),
        ("general_findings", "members can manage general findings"),
        ("project_conclusions", "members can manage conclusions"),
        ("plan_files", "members can manage plan files"),
        ("plan_markers", "members can manage plan markers"),
        ("ai_jobs", "members can read ai jobs"),
        ("report_versions", "members can read report versions"),
        ("activity_events", "members can read activity"),
        ("report_preview_confirmations", "members can manage report preview confirmations"),
    ]
    for key in protected_policy_names:
        assert key in policies
        assert "private.current_user_is_active()" in policies[key]


@pytest.mark.skipif(
    not MIGRATIONS_DIR.exists(),
    reason="Supabase migrations are outside standalone backend checkouts.",
)
def test_trades_are_read_only_for_authenticated_clients() -> None:
    policies = _final_policy_definitions()

    assert ("trades", "active users can manage trades") not in policies
    assert ("trades", "active users can read trades") in policies
    assert "for select" in policies[("trades", "active users can read trades")]
    assert "private.current_user_is_active()" in policies[
        ("trades", "active users can read trades")
    ]


@pytest.mark.skipif(
    not SUPABASE_CONFIG.exists(),
    reason="Supabase config is outside standalone backend checkouts.",
)
def test_supabase_auth_config_is_invite_only_and_hardened() -> None:
    config = SUPABASE_CONFIG.read_text(encoding="utf-8")

    assert "enable_signup = false" in config
    assert "additional_redirect_urls = [\"bba-baudoku://reset-password\"" in config
    assert "minimum_password_length = 12" in config
    assert 'password_requirements = "lower_upper_letters_digits_symbols"' in config
    assert "secure_password_change = true" in config


def test_unknown_supabase_user_is_not_auto_activated() -> None:
    repository = ProfileProvisioningRepository()

    user = repository.ensure_profile(
        AuthenticatedUser(
            id="99999999-9999-4999-8999-999999999999",
            email="unknown@example.com",
            display_name="Unknown",
        )
    )

    assert user.is_active is False
    assert repository.inserted_profiles == [
        {
            "id": "99999999-9999-4999-8999-999999999999",
            "email": "unknown@example.com",
            "display_name": "Unknown",
            "is_active": False,
        }
    ]


class ProfileProvisioningRepository(SupabaseProjectRepository):
    def __init__(self) -> None:
        self.inserted_profiles: list[dict[str, object]] = []

    @property
    def _client(self) -> "ProfileProvisioningRepository":
        return self

    def _select_one(self, table: str, column: str, value: str) -> None:
        assert table == "profiles"
        assert column == "id"
        assert value == "99999999-9999-4999-8999-999999999999"
        return None

    def table(self, table: str) -> "ProfileProvisioningRepository":
        assert table == "profiles"
        return self

    def insert(self, payload: dict[str, object]) -> "ProfileProvisioningRepository":
        self.inserted_profiles.append(payload)
        return self

    def _execute(self, query: object) -> object:
        return query


def _final_policy_definitions() -> dict[tuple[str, str], str]:
    policies: dict[tuple[str, str], str] = {}
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        _apply_policy_drops(policies, sql)
        _apply_policy_creates(policies, sql)
    return policies


def _apply_policy_drops(policies: dict[tuple[str, str], str], sql: str) -> None:
    marker = "drop policy if exists "
    for statement in sql.split(";"):
        normalized = " ".join(statement.split())
        if not normalized.lower().startswith(marker):
            continue
        rest = normalized[len(marker) :]
        policy_name, _, table_part = rest.partition(" on public.")
        policies.pop((table_part.strip(), policy_name.strip('"')), None)


def _apply_policy_creates(policies: dict[tuple[str, str], str], sql: str) -> None:
    for statement in sql.split(";"):
        normalized = " ".join(statement.split())
        if not normalized.lower().startswith("create policy "):
            continue
        policy_name, _, rest = normalized[len("create policy ") :].partition(
            " on public."
        )
        table_name = rest.split(" ", maxsplit=1)[0]
        policies[(table_name, policy_name.strip('"'))] = normalized.lower()
