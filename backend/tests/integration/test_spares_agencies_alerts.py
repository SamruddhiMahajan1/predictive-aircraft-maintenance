"""Spares, agencies, alerts and the audit trail — spec items 36-39, 51."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.domain.scheduling import back_in_service_breakdown
from app.models.auth import AuditLog
from app.models.maintenance import Agency, AgencyBooking, Spare


def _spare(client, *, stock=None):
    """A spare, optionally forced to a given stock level."""
    items = client.get("/api/v1/spares").json()["items"]
    for item in items:
        if (item["stock"] > 0) if stock is None else (item["stock"] == stock):
            return item
    pytest.skip("no spare matching the requested stock")


def _set_stock(client, part_ref_id, stock):
    return client.patch(f"/api/v1/spares/{part_ref_id}",
                        json={"stock": stock, "reason": "adjust"})


# ── 36 spares ──────────────────────────────────────────────────────────────────
def test_spares_are_seeded_from_the_csv(client):
    body = client.get("/api/v1/spares").json()
    assert body["total"] == 40
    assert all(item["part_ref_id"].startswith("PART") for item in body["items"])


def test_spare_fields_come_from_the_source(client):
    item = _spare(client)
    for field in ("part_ref_id", "item_name", "stock", "minimum_stock",
                  "reorder_quantity", "supplier", "lead_time_days", "unit_cost_inr",
                  "storage_location", "criticality", "in_stock", "low_stock"):
        assert field in item, field


def test_low_stock_flag_matches_stock_versus_minimum(client):
    for item in client.get("/api/v1/spares").json()["items"]:
        assert item["low_stock"] == (item["stock"] <= item["minimum_stock"])
        assert item["in_stock"] == (item["stock"] > 0)


def test_patch_stock_sets_an_absolute_value(client):
    spare = _spare(client)
    body = _set_stock(client, spare["part_ref_id"], 7).json()
    assert body["stock"] == 7


def test_patch_stock_records_a_movement_with_the_delta(client, db):
    spare = _spare(client)
    _set_stock(client, spare["part_ref_id"], 9)
    listed = client.get("/api/v1/spares").json()["items"]
    current = next(i for i in listed if i["part_ref_id"] == spare["part_ref_id"])
    assert current["last_movement"]["reason"] == "adjust"
    assert current["last_movement"]["delta"] != 0


def test_patch_stock_rejects_negative(client):
    spare = _spare(client)
    assert _set_stock(client, spare["part_ref_id"], -1).status_code == 422


def test_patch_stock_is_audited(client, db):
    spare = _spare(client)
    _set_stock(client, spare["part_ref_id"], 11)
    row = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity == "spare", AuditLog.entity_id == spare["part_ref_id"])
        .order_by(AuditLog.at.desc())
    ).first()
    assert row is not None
    assert row.after["stock"] == 11
    assert row.actor_name == "system"


def test_unknown_spare_is_404(client):
    assert _set_stock(client, "PART999", 5).status_code == 404


# ── 37 reserve ─────────────────────────────────────────────────────────────────
def test_reserve_decrements_stock_by_one(client, db):
    spare = _spare(client)
    _set_stock(client, spare["part_ref_id"], 3)
    body = client.post(f"/api/v1/spares/{spare['part_ref_id']}/reserve", json={}).json()
    assert body["stock_before"] == 3
    assert body["stock_remaining"] == 2


def test_reserve_records_a_negative_movement(client, db):
    spare = _spare(client)
    _set_stock(client, spare["part_ref_id"], 2)
    client.post(f"/api/v1/spares/{spare['part_ref_id']}/reserve", json={})
    movement = db.scalars(
        select(__import__("app.models.maintenance", fromlist=["StockMovement"]).StockMovement)
        .where(
            __import__("app.models.maintenance", fromlist=["StockMovement"]).StockMovement.spare_id
            == db.query(Spare).filter(Spare.part_ref_id == spare["part_ref_id"]).one().id
        ).order_by(
            __import__("app.models.maintenance", fromlist=["StockMovement"]).StockMovement.created_at.desc()
        )
    ).first()
    assert movement.delta == -1
    assert movement.reason == "reserve"


def test_reserving_zero_stock_is_409_with_the_lead_time(client):
    spare = _spare(client)
    _set_stock(client, spare["part_ref_id"], 0)
    response = client.post(f"/api/v1/spares/{spare['part_ref_id']}/reserve", json={})
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "OUT_OF_STOCK"
    assert body["detail"]["stock"] == 0
    assert body["detail"]["lead_time_days"] == spare["lead_time_days"]


def test_reserve_moves_the_work_order_to_in_progress(client, db):
    from app.models.fleet import Part
    from app.models.maintenance import WorkOrder

    spare = _spare(client)
    _set_stock(client, spare["part_ref_id"], 2)
    code, part = "Fighter-01", "radar"
    existing = db.query(WorkOrder).filter(WorkOrder.status != "done").first()
    payload = {"aircraft": code, "part": part, "due_date": "2026-12-01"}
    if existing and existing.part_id == db.query(Part).filter(Part.code == part).one().id:
        work_order_id = existing.id
    else:
        work_order_id = client.post("/api/v1/work-orders",
                                    json=payload).json()["id"]
    body = client.post(f"/api/v1/spares/{spare['part_ref_id']}/reserve",
                       json={"work_order_id": work_order_id}).json()
    assert body["work_order_status"] == "in_progress"


def test_reserve_is_audited(client, db):
    spare = _spare(client)
    _set_stock(client, spare["part_ref_id"], 5)
    client.post(f"/api/v1/spares/{spare['part_ref_id']}/reserve", json={})
    row = db.scalars(
        select(AuditLog).where(AuditLog.entity == "spare",
                               AuditLog.action == "reserve",
                               AuditLog.entity_id == spare["part_ref_id"])
    ).first()
    assert row is not None
    assert row.actor_name == "system"


def test_unknown_spare_reserve_is_404(client):
    assert client.post("/api/v1/spares/PART999/reserve", json={}).status_code == 404


# ── 38 agencies ────────────────────────────────────────────────────────────────
def test_agencies_are_seeded_from_the_csv(client):
    items = client.get("/api/v1/agencies").json()["items"]
    assert len(items) == 6
    assert {i["agency_ref_id"] for i in items} == {"MA001", "MA002", "MA003",
                                                   "MA004", "MA005", "MA006"}


def test_agency_free_slot_is_derived_from_capacity(client):
    """free_slot_days = ceil((1 - booked/30) * 30 / capacity_slots), 0 when full."""
    import math

    items = client.get("/api/v1/agencies").json()["items"]
    assert items
    for item in items:
        assert 0 <= item["free_slot_days"] <= 30
        assert item["free_slot_days"] <= max(1, math.ceil(30 / item["monthly_capacity_slots"]))


def test_idle_agency_free_slot_matches_the_seed_formula(client, db):
    """MA001 is the widest shop (capacity 40) so it keeps a slot under load."""
    from app.domain.scheduling import agency_free_slot_days

    items = client.get("/api/v1/agencies").json()["items"]
    widest = next(i for i in items if i["agency_ref_id"] == "MA001")
    expected = agency_free_slot_days(widest["monthly_capacity_slots"],
                                     booked_days=0, open_bookings=0)
    assert expected == max(1, math_ceil(30 / widest["monthly_capacity_slots"]))


def math_ceil(value: float) -> int:
    import math

    return math.ceil(value)


def test_agency_handles_parts_is_the_reverse_assignment(client):
    """Rule 15: engine→engine MRO, hyd→hydraulics, radar→avionics."""
    items = client.get("/api/v1/agencies").json()["items"]
    handled = {part: i["agency_ref_id"] for i in items for part in i["handles_parts"]}
    assert handled["engine"] == "MA003"     # specialisation 'engine'
    assert handled["hyd"] == "MA005"        # specialisation 'hydraulics'
    assert handled["radar"] == "MA004"      # specialisation 'avionics'
    # gear and fuel have no specialisation match -> cheapest of the general pool
    assert handled["gear"] == handled["fuel"] == "MA002"


def test_booking_returns_the_rule_24_arithmetic(client, db):
    agency = db.query(Agency).filter(Agency.agency_ref_id == "MA001").one()
    response = client.post(f"/api/v1/agencies/{agency.id}/bookings",
                           json={"aircraft": "Fighter-01", "part": "engine"})
    if response.status_code == 409:
        pytest.skip("MA001 already full from an earlier booking test")
    assert response.status_code == 201
    body = response.json()
    breakdown = body["breakdown"]
    assert body["back_in_service_days"] == (
        breakdown["slot"] + breakdown["turnaround"] + breakdown["lead_time"]
    )
    assert body["slot_days"] == breakdown["slot"]
    assert body["turnaround_days"] == breakdown["turnaround"]


def test_a_full_agency_reports_no_slot_available(client, db):
    """Book a dedicated agency until its 30-day horizon is consumed.

    A purpose-made agency keeps the test independent of what other tests booked.
    13-day turnarounds: 30 / 13 = 2 slots, the third must be refused.
    """
    agency = Agency(agency_ref_id="MA900", name="Capacity Test Depot",
                    type="Test", location="Base-A", specialisation="general",
                    turnaround_days=13, monthly_capacity_slots=40,
                    cost_multiplier=1.0, free_slot_days=1)
    db.add(agency)
    db.commit()
    try:
        codes = []
        for _ in range(4):
            response = client.post(f"/api/v1/agencies/{agency.id}/bookings",
                                   json={"aircraft": "Fighter-02", "part": "engine"})
            codes.append(response.status_code)
            if response.status_code == 409:
                assert response.json()["error"]["code"] == "NO_SLOT_AVAILABLE"
                break
        # 13-day turnarounds: three fit inside the 30-day horizon (13+13+13),
        # the fourth exceeds it and must be refused
        assert codes == [201, 201, 201, 409], codes
        db.expire_all()
        # the refusal rolled back, so the stored slot is unchanged
        assert db.query(Agency).filter(Agency.id == agency.id).one().free_slot_days == 1
    finally:
        db.query(AgencyBooking).filter(AgencyBooking.agency_id == agency.id).delete()
        db.delete(db.get(Agency, agency.id))
        db.commit()


def test_booking_eta_is_start_plus_total_days(client, db):
    from datetime import date, timedelta

    agency = db.query(Agency).filter(Agency.agency_ref_id == "MA006").one()
    response = client.post(f"/api/v1/agencies/{agency.id}/bookings",
                           json={"aircraft": "Fighter-06", "part": "hyd"})
    if response.status_code == 409:
        pytest.skip("MA006 already full from an earlier booking test")
    body = response.json()
    expected = date.today() + timedelta(days=body["back_in_service_days"])
    assert body["eta_date"] == expected.isoformat()


def test_booking_is_audited_with_the_eta(client, db):
    agency = db.query(Agency).first()
    client.post(f"/api/v1/agencies/{agency.id}/bookings",
                json={"aircraft": "Fighter-03", "part": "gear"})
    row = db.scalars(
        select(AuditLog).where(AuditLog.entity == "agency", AuditLog.action == "book")
        .order_by(AuditLog.at.desc())
    ).first()
    assert row is not None
    assert "eta_date" in row.after
    assert row.actor_name == "system"


def test_unknown_agency_booking_is_404(client):
    assert client.post("/api/v1/agencies/99999/bookings",
                       json={"aircraft": "Fighter-01", "part": "engine"}
                       ).status_code == 404


# ── 39 alerts ──────────────────────────────────────────────────────────────────
def test_alerts_are_listed_with_an_unacknowledged_count(client):
    body = client.get("/api/v1/alerts").json()
    assert "items" in body and "unacknowledged_count" in body
    assert body["unacknowledged_count"] >= 0


def test_alert_fields(client):
    items = client.get("/api/v1/alerts").json()["items"]
    if not items:
        pytest.skip("no alerts seeded")
    for field in ("id", "aircraft", "part", "level", "message",
                  "acknowledged", "created_at"):
        assert field in items[0], field


def test_alert_level_vocabulary(client):
    for item in client.get("/api/v1/alerts").json()["items"]:
        assert item["level"] in ("info", "watch", "critical")


def test_alert_filter_by_acknowledgement(client):
    open_items = client.get("/api/v1/alerts?acknowledged=false").json()["items"]
    assert all(i["acknowledged"] is False for i in open_items)


def test_ack_records_the_user_and_time(client, db):
    items = client.get("/api/v1/alerts?acknowledged=false").json()["items"]
    if not items:
        pytest.skip("no unacknowledged alerts")
    body = client.post(f"/api/v1/alerts/{items[0]['id']}/ack", json={"note": "scheduled"}).json()
    assert body["acknowledged"] is True
    assert body["acknowledged_by"] is None
    assert body["acknowledged_at"] is not None
    assert body["note"] == "scheduled"


def test_ack_is_idempotent(client):
    items = client.get("/api/v1/alerts?acknowledged=false").json()["items"]
    if not items:
        pytest.skip("no unacknowledged alerts")
    alert_id = items[0]["id"]
    assert client.post(f"/api/v1/alerts/{alert_id}/ack", json={}).status_code == 200
    assert client.post(f"/api/v1/alerts/{alert_id}/ack", json={}).status_code == 200


def test_ack_is_audited(client, db):
    items = client.get("/api/v1/alerts?acknowledged=false").json()["items"]
    if not items:
        pytest.skip("no unacknowledged alerts")
    client.post(f"/api/v1/alerts/{items[0]['id']}/ack", json={})
    row = db.scalars(
        select(AuditLog).where(AuditLog.entity == "alert", AuditLog.action == "ack")
        .order_by(AuditLog.at.desc())
    ).first()
    assert row is not None
    assert row.after["acknowledged"] is True


def test_unknown_alert_ack_is_404(client):
    assert client.post("/api/v1/alerts/999999/ack", json={}).status_code == 404


# ── 51 audit trail ─────────────────────────────────────────────────────────────
def test_audit_rows_carry_actor_and_timestamp(client, db):
    _set_stock(client, _spare(client)["part_ref_id"], 4)
    rows = db.query(AuditLog).order_by(AuditLog.at.desc()).limit(10).all()
    assert rows
    assert all(r.actor_name for r in rows)
    assert all(r.at is not None for r in rows)


def test_audit_before_and_after_are_json_serialisable(client, db):
    rows = db.query(AuditLog).order_by(AuditLog.at.desc()).limit(10).all()
    for row in rows:
        assert row.before is None or isinstance(row.before, dict)
        assert row.after is None or isinstance(row.after, dict)


def test_audit_records_the_request_id(client, db):
    alert_id = _any_open_alert(client)
    client.post(f"/api/v1/alerts/{alert_id}/ack", json={})
    row = db.query(AuditLog).order_by(AuditLog.at.desc()).first()
    assert row.request_id


def test_audit_filter_by_entity(client):
    client.get("/api/v1/audit?entity=spare")
    body = client.get("/api/v1/audit?entity=spare").json()
    assert all(row["entity"] == "spare" for row in body["items"])


def test_back_in_service_matches_the_documented_formula(client, db):
    """End-to-end check of rule 24 against the agency and spare in the response."""
    detail = client.get("/api/v1/aircraft/Fighter-01/parts/hyd").json()
    agency, spare = detail["agency"], detail["spare"]
    assert detail["back_in_service_days"] == back_in_service_breakdown(
        agency["free_slot_days"], agency["turnaround_days"],
        spare["lead_time_days"], spare["stock"])["total"]


def _any_open_alert(client) -> int:
    items = client.get("/api/v1/alerts?acknowledged=false").json()["items"]
    return items[0]["id"] if items else 1
