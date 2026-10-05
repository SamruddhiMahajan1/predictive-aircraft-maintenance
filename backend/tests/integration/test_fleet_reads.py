"""Fleet read endpoints — spec items 27-34, against the seeded database."""
from __future__ import annotations

from contextlib import contextmanager

import pytest

PARTS = ["engine", "radar", "gear", "hyd", "fuel"]
RISKS = {"healthy", "watch", "critical"}


@contextmanager
def frozen_replay(client):
    """Hold the replay still so two reads see the same data.

    The replay engine advances all eight aircraft every 1.2 s for the whole session, so any
    assertion spanning two HTTP requests compares two different snapshots. Pausing is the
    only way to make a cross-endpoint relationship checkable — and without it those
    assertions fail intermittently rather than deterministically, which is the worst kind.
    """
    client.post("/api/v1/demo/pause")
    try:
        yield
    finally:
        client.post("/api/v1/demo/resume")


# ── 27 /fleet/summary ──────────────────────────────────────────────────────────
def test_summary_shape(client):
    body = client.get("/api/v1/fleet/summary").json()
    for field in ("mission_ready_count", "total_aircraft", "critical_parts",
                  "average_rul", "lowest_rul_aircraft", "risk_breakdown",
                  "series", "generated_at"):
        assert field in body, field


def test_summary_counts_the_seeded_fleet(client):
    body = client.get("/api/v1/fleet/summary").json()
    assert body["total_aircraft"] == 8
    assert body["mission_ready_count"] <= 8
    assert body["risk_breakdown"]["healthy"] + body["risk_breakdown"]["watch"] \
        + body["risk_breakdown"]["critical"] == 40      # 8 aircraft x 5 parts


def test_summary_lowest_rul_is_the_minimum(client):
    # Two endpoints, so two snapshots — RUL moves every 1.2 s while the replay runs.
    with frozen_replay(client):
        summary = client.get("/api/v1/fleet/summary").json()
        fleet = client.get("/api/v1/aircraft").json()
        assert summary["lowest_rul_aircraft"]["rul"] == min(a["rul"] for a in fleet["items"])


def test_summary_average_rul_is_within_range(client):
    body = client.get("/api/v1/fleet/summary").json()
    assert 0 <= body["average_rul"] <= 125


def test_summary_series_cycles_align_across_both_lines(client):
    series = client.get("/api/v1/fleet/summary").json()["series"]
    avg = [p["cycle"] for p in series["fleet_avg_health"]]
    weak = [p["cycle"] for p in series["weakest_aircraft_health"]]
    assert avg == weak


def test_summary_window_is_respected(client):
    for window in (1, 10, 60):
        body = client.get(f"/api/v1/fleet/summary?window={window}").json()
        assert body["series"]["window"] <= window


def test_summary_rejects_an_absurd_window(client):
    response = client.get("/api/v1/fleet/summary?window=100000")
    assert response.status_code == 422


def test_summary_avg_availability_is_a_ratio(client):
    body = client.get("/api/v1/fleet/summary").json()
    assert body["avg_availability"] is None or 0.0 <= body["avg_availability"] <= 1.0


# ── 28 /aircraft ───────────────────────────────────────────────────────────────
def test_aircraft_list_returns_the_eight_seeded_units(client):
    body = client.get("/api/v1/aircraft").json()
    assert body["total"] == 8
    assert [a["code"] for a in body["items"]] == [f"Fighter-0{i}" for i in range(1, 9)]


def test_aircraft_list_item_fields(client):
    item = client.get("/api/v1/aircraft").json()["items"][0]
    for field in ("id", "code", "mission_ready", "rul", "worst_part", "risk",
                  "engine_health", "parts"):
        assert field in item, field
    assert set(item["parts"]) == set(PARTS)
    assert item["risk"] in RISKS


def test_aircraft_rul_is_capped_at_125(client):
    for item in client.get("/api/v1/aircraft").json()["items"]:
        assert 0 <= item["rul"] <= 125


@pytest.mark.parametrize("risk", ["healthy", "watch", "critical"])
def test_aircraft_filter_by_risk(client, risk):
    body = client.get(f"/api/v1/aircraft?risk={risk}").json()
    assert all(a["risk"] == risk for a in body["items"])


def test_aircraft_filter_by_readiness(client):
    body = client.get("/api/v1/aircraft?ready=true").json()
    assert all(a["mission_ready"] for a in body["items"])


def test_aircraft_rejects_an_unknown_risk_filter(client):
    assert client.get("/api/v1/aircraft?risk=banana").status_code == 422


# ── 29 /aircraft/{id} ──────────────────────────────────────────────────────────
def test_aircraft_detail_by_code(client):
    body = client.get("/api/v1/aircraft/Fighter-01").json()
    assert body["code"] == "Fighter-01"
    assert [p["part"] for p in body["parts"]] == PARTS


def test_aircraft_detail_by_numeric_id(client):
    with frozen_replay(client):
        by_code = client.get("/api/v1/aircraft/Fighter-01").json()
        by_id = client.get(f"/api/v1/aircraft/{by_code['id']}").json()
        assert by_code["code"] == by_id["code"]


def test_aircraft_detail_flags_simulated_parts(client):
    parts = client.get("/api/v1/aircraft/Fighter-01").json()["parts"]
    by_code = {p["part"]: p for p in parts}
    assert by_code["engine"]["simulated"] is False
    assert by_code["engine"]["method"] == "rul_xgb_fd001"
    for code in ("radar", "gear", "hyd", "fuel"):
        assert by_code[code]["simulated"] is True
        assert by_code[code]["method"] == "maintenance_burden_v1"


def test_aircraft_detail_health_is_in_range(client):
    parts = client.get("/api/v1/aircraft/Fighter-01").json()["parts"]
    assert all(0.0 <= p["health"] <= 1.0 for p in parts)


def test_aircraft_detail_risk_matches_health(client):
    from app.domain.rules import risk_level

    for code in [f"Fighter-0{i}" for i in range(1, 9)]:
        for p in client.get(f"/api/v1/aircraft/{code}").json()["parts"]:
            assert p["risk"] == risk_level(p["health"])


def test_unknown_aircraft_is_404(client):
    response = client.get("/api/v1/aircraft/Fighter-99")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# ── 30 /aircraft/{id}/engine ───────────────────────────────────────────────────
def test_engine_detail_fields(client):
    body = client.get("/api/v1/aircraft/Fighter-01/engine").json()
    for field in ("rul", "components", "top_sensors", "component_sensor_map",
                  "history", "model", "health", "risk"):
        assert field in body, field


def test_engine_components_are_the_four_spec_components(client):
    body = client.get("/api/v1/aircraft/Fighter-01/engine").json()
    assert set(body["components"]) == {"fan", "hpc", "hpt", "lpt"}
    present = [v for v in body["components"].values() if v is not None]
    assert all(0.0 <= v <= 1.0 for v in present)


def test_engine_component_map_matches_the_spec(client):
    body = client.get("/api/v1/aircraft/Fighter-01/engine").json()
    assert body["component_sensor_map"] == {
        # s9 added to hpc: highest end-of-life deviation and 7.8% of model gain
        "fan": ["s8", "s13"], "hpc": ["s3", "s7", "s9", "s11"],
        "hpt": ["s20", "s21"], "lpt": ["s4"],
    }


def test_engine_weakest_component_has_the_lowest_health(client):
    """With no telemetry yet every component is null and there is no weakest."""
    for code in [f"Fighter-0{i}" for i in range(1, 9)]:
        body = client.get(f"/api/v1/aircraft/{code}/engine").json()
        components = body["components"]
        present = {k: v for k, v in components.items() if v is not None}
        if not present:
            assert body["weakest_component"] is None
            continue
        assert components[body["weakest_component"]] == min(present.values())


def test_engine_window_is_honoured(client):
    body = client.get("/api/v1/aircraft/Fighter-01/engine?window=5").json()
    assert len(body["history"]) <= 5


def test_engine_history_is_ordered_oldest_first(client):
    history = client.get("/api/v1/aircraft/Fighter-01/engine").json()["history"]
    cycles = [h["cycle"] for h in history]
    assert cycles == sorted(cycles)


def test_engine_top_sensors_are_capped_at_five(client):
    body = client.get("/api/v1/aircraft/Fighter-01/engine").json()
    assert len(body["top_sensors"]) <= 5


def test_engine_model_block_reports_the_fallback(client):
    model = client.get("/api/v1/aircraft/Fighter-01/engine").json()["model"]
    assert "version" in model
    assert "loaded" in model or "fallback" in model


def test_engine_rul_is_capped(client):
    body = client.get("/api/v1/aircraft/Fighter-01/engine").json()
    assert 0 <= body["rul"] <= 125


# ── 31 /aircraft/{id}/parts/{part} ─────────────────────────────────────────────
@pytest.mark.parametrize("part", PARTS)
def test_part_detail_for_every_part(client, part):
    body = client.get(f"/api/v1/aircraft/Fighter-01/parts/{part}").json()
    assert body["part"] == part
    assert body["label"]
    assert 0.0 <= body["health"] <= 1.0
    assert body["action"] in ("Routine check", "Plan inspection", "Replace now")


def test_part_detail_returns_at_most_two_records(client):
    body = client.get("/api/v1/aircraft/Fighter-01/parts/engine").json()
    assert len(body["records"]) <= 2


def test_part_detail_exposes_the_rule_24_arithmetic(client):
    body = client.get("/api/v1/aircraft/Fighter-01/parts/hyd").json()
    breakdown = body["back_in_service_breakdown"]
    assert body["back_in_service_days"] == (
        breakdown["slot_days"] + breakdown["turnaround_days"] + breakdown["lead_time_days"]
    )
    assert breakdown["lead_time_applied"] == (breakdown["lead_time_days"] > 0)


def test_part_detail_doby_is_null_for_a_simulated_part(client):
    body = client.get("/api/v1/aircraft/Fighter-01/parts/hyd").json()
    assert body["rul"] is None
    assert body["do_by_cycle"] is None


def test_part_detail_engine_carries_components(client):
    body = client.get("/api/v1/aircraft/Fighter-01/parts/engine").json()
    assert body["components"] is not None
    assert set(body["components"]) == {"fan", "hpc", "hpt", "lpt"}


def test_unknown_part_is_422(client):
    response = client.get("/api/v1/aircraft/Fighter-01/parts/antenna")
    assert response.status_code == 422


# ── 32 /fleet/heatmap ──────────────────────────────────────────────────────────
def test_heatmap_is_eight_by_five(client):
    body = client.get("/api/v1/fleet/heatmap").json()
    assert body["parts"] == PARTS
    assert len(body["aircraft"]) == 8
    assert all(len(row["cells"]) == 5 for row in body["aircraft"])


def test_heatmap_legend_states_the_band_boundaries(client):
    legend = client.get("/api/v1/fleet/heatmap").json()["legend"]
    assert "0.70" in legend["healthy"]
    assert "0.40" in legend["watch"]


def test_heatmap_cells_carry_the_simulated_flag(client):
    cells = client.get("/api/v1/fleet/heatmap").json()["aircraft"][0]["cells"]
    engine = next(c for c in cells if c["part"] == "engine")
    radar = next(c for c in cells if c["part"] == "radar")
    assert engine["simulated"] is False
    assert radar["simulated"] is True


# ── 33 /fleet/actions ──────────────────────────────────────────────────────────
def test_actions_are_ranked_worst_first(client):
    body = client.get("/api/v1/fleet/actions?limit=5").json()
    healths = [i["health"] for i in body["items"]]
    assert healths == sorted(healths)
    assert [i["rank"] for i in body["items"]] == [1, 2, 3, 4, 5]


def test_actions_default_limit_is_five(client):
    body = client.get("/api/v1/fleet/actions").json()
    assert body["limit"] == 5
    assert len(body["items"]) <= 5


def test_actions_respect_a_larger_limit(client):
    body = client.get("/api/v1/fleet/actions?limit=50").json()
    assert len(body["items"]) <= 40


def test_actions_reject_a_limit_over_fifty(client):
    assert client.get("/api/v1/fleet/actions?limit=500").status_code == 422


def test_actions_carry_action_spare_and_agency(client):
    item = client.get("/api/v1/fleet/actions?limit=1").json()["items"][0]
    for field in ("aircraft", "part", "health", "risk", "action",
                  "spare", "agency", "back_in_service_days"):
        assert field in item, field


# ── 34 /maintenance/schedule ───────────────────────────────────────────────────
def test_schedule_has_one_row_per_aircraft(client):
    items = client.get("/api/v1/maintenance/schedule").json()["items"]
    assert len(items) == 8
    assert len({row["aircraft"] for row in items}) == 8


def test_schedule_worst_part_is_the_lowest_health(client):
    # Sixteen sequential requests against a fleet being rewritten underneath them: without
    # the pause a part's health can change between the schedule row and the detail read, and
    # this failed roughly one run in three.
    with frozen_replay(client):
        for row in client.get("/api/v1/maintenance/schedule").json()["items"]:
            detail = client.get(f"/api/v1/aircraft/{row['aircraft']}").json()
            lowest = min(p["health"] for p in detail["parts"])
            assert row["worst_health"] == pytest.approx(lowest, abs=1e-3)


def test_schedule_spare_status_vocabulary(client):
    allowed = {"in_stock", "low", "out_of_stock", "none"}
    for row in client.get("/api/v1/maintenance/schedule").json()["items"]:
        assert row["spare_status"] in allowed, row


def test_schedule_action_matches_the_risk_band(client):
    from app.domain.rules import recommended_action

    for row in client.get("/api/v1/maintenance/schedule").json()["items"]:
        assert row["action"] == recommended_action(row["risk"])
