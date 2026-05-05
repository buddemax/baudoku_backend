from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SEED_SQL = ROOT / "supabase" / "seed.sql"


def test_seed_sql_contains_initial_bba_trade_list() -> None:
    seed_sql = SEED_SQL.read_text(encoding="utf-8")

    expected_trades = [
        "Abdichtung",
        "Dach",
        "Fenster",
        "Fassade",
        "Elektro",
        "Heizung",
        "Sanitaer",
        "Lueftung",
        "Trockenbau",
        "Brandschutz",
    ]

    for trade in expected_trades:
        assert f"('{trade}')" in seed_sql
    assert "on conflict (name) do nothing" in seed_sql.lower()
