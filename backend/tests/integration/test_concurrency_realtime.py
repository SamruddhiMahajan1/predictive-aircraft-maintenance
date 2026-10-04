"""Concurrency (spec 37/38) and the realtime protocol (spec 42/43)."""
from __future__ import annotations

import threading

import pytest

from app.models.auth import AuditLog
from app.models.maintenance import Agency, AgencyBooking, Spare, StockMovement


def _set_stock(client, auth, part_ref_id, stock):
    return client.patch(f"/api/v1/spares/{part_ref_id}", headers=auth("officer"),
                        json={"stock": stock, "reason": "adjust"})


# ── 37 no oversell under concurrent reservations ───────────────────────────────
def test_twenty_concurrent_reservations_never_oversell(client, auth, db):
    spare_ref = next(
        i["part_ref_id"] for i in
        client.get("/api/v1/spares", headers=auth("viewer")).json()["items"]
    )
    _set_stock(client, auth, spare_ref, 1)

    results: list[int] = []
    lock = threading.Lock()

    def reserve() -> None:
        code = client.post(f"/api/v1/spares/{spare_ref}/reserve",
                           headers=auth("officer"), json={}).status_code
        with lock:
            results.append(code)

    threads = [threading.Thread(target=reserve) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(200) == 1, f"expected exactly one winner, got {results}"
    assert results.count(409) == 19
    db.expire_all()
    assert db.query(Spare).filter(Spare.part_ref_id == spare_ref).one().stock == 0


def test_concurrent_reservations_record_one_movement_each(client, auth, db):
    spare_ref = next(
        i["part_ref_id"] for i in
        client.get("/api/v1/spares", headers=auth("viewer")).json()["items"]
    )
    _set_stock(client, auth, spare_ref, 3)
    spare_id = db.query(Spare).filter(Spare.part_ref_id == spare_ref).one().id
    before = db.query(StockMovement).filter(
        StockMovement.spare_id == spare_id, StockMovement.reason == "reserve"
    ).count()

    def reserve() -> None:
        client.post(f"/api/v1/spares/{spare_ref}/reserve",
                    headers=auth("officer"), json={})

    threads = [threading.Thread(target=reserve) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    db.expire_all()
    reserves = db.query(StockMovement).filter(
        StockMovement.spare_id == spare_id,
        StockMovement.reason == "reserve",
    ).count()
    assert reserves - before == 3   # exactly the stock that existed


# ── 38 concurrent bookings ────────────────────────────────────────────────────
def test_concurrent_bookings_all_succeed_while_slots_remain(client, auth, db):
    agency = db.query(Agency).first()
    results: list[int] = []
    lock = threading.Lock()

    def book() -> None:
        code = client.post(f"/api/v1/agencies/{agency.id}/bookings",
                           headers=auth("officer"),
                           json={"aircraft": "Fighter-01", "part": "engine"}).status_code
        with lock:
            results.append(code)

    threads = [threading.Thread(target=book) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # capacity is finite: a 24-day turnaround only fits once in a 30-day horizon,
    # so exactly one booking wins and the rest are told there is no slot
    assert results.count(201) >= 1, results
    assert set(results) <= {201, 409}, results
    db.expire_all()
    assert db.query(Agency).filter(Agency.id == agency.id).one().free_slot_days >= 0
    assert (db.query(AgencyBooking).filter(
        AgencyBooking.agency_id == agency.id, AgencyBooking.completed_at.is_(None)
    ).count() == results.count(201))


def test_each_booking_is_audited_with_its_eta(client, auth, db):
    agency = db.query(Agency).first()
    client.post(f"/api/v1/agencies/{agency.id}/bookings", headers=auth("officer"),
                json={"aircraft": "Fighter-04", "part": "radar"})
    rows = db.query(AuditLog).filter(AuditLog.entity == "agency").all()
    assert rows
    assert all("eta_date" in row.after for row in rows)


def test_booking_free_slot_is_monotonically_non_increasing(client, auth, db):
    from app.models.maintenance import Agency

    agency = db.query(Agency).filter(Agency.turnaround_days == 24).one()
    previous = agency.free_slot_days
    for code in ("Fighter-05", "Fighter-06", "Fighter-07"):
        client.post(f"/api/v1/agencies/{agency.id}/bookings", headers=auth("officer"),
                    json={"aircraft": code, "part": "gear"})
        db.expire_all()
        current = db.query(Agency).filter(Agency.id == agency.id).one().free_slot_days
        assert current <= previous, f"{previous} -> {current} must not increase"
        previous = current


# ── 42 WebSocket ──────────────────────────────────────────────────────────────
def test_websocket_rejects_a_missing_token(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/fleet") as ws:
        ws.receive_json()


def test_websocket_rejects_a_bad_token_with_4401(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/fleet?token=garbage") as ws:
            ws.receive_json()


def test_websocket_sends_connection_ready(client, tokens):
    with client.websocket_connect(f"/ws/fleet?token={tokens['viewer']}") as ws:
        message = ws.receive_json()
    assert message["type"] == "connection.ready"
    assert message["payload"]["aircraft"] == 8
    assert message["payload"]["protocol_version"] == 1


def test_websocket_answers_ping_with_pong(client, tokens):
    with client.websocket_connect(f"/ws/fleet?token={tokens['viewer']}") as ws:
        ws.receive_json()                       # connection.ready
        ws.send_json({"type": "ping", "payload": {}})
        assert ws.receive_json()["type"] == "pong"


def test_websocket_accepts_subscribe(client, tokens):
    with client.websocket_connect(f"/ws/fleet?token={tokens['viewer']}") as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe", "payload": {"aircraft": ["Fighter-01"]}})
        ws.send_json({"type": "ping", "payload": {}})
        assert ws.receive_json()["type"] == "pong"


def test_websocket_ignores_unknown_message_types(client, tokens):
    with client.websocket_connect(f"/ws/fleet?token={tokens['viewer']}") as ws:
        ws.receive_json()
        ws.send_json({"type": "nonsense", "payload": {}})
        ws.send_json({"type": "ping", "payload": {}})
        assert ws.receive_json()["type"] == "pong"


def test_websocket_disconnect_unregisters(client, tokens):
    from app.realtime.bus import bus

    before = bus.subscriber_count
    with client.websocket_connect(f"/ws/fleet?token={tokens['viewer']}") as ws:
        ws.receive_json()
    assert bus.subscriber_count == before


# ── 43 demo controls ──────────────────────────────────────────────────────────
def test_demo_status_reports_the_replay_state(client, auth):
    body = client.get("/api/v1/demo/status", headers=auth("commander")).json()
    for field in ("running", "paused", "tick", "interval_seconds", "subscribers"):
        assert field in body


def test_pause_and_resume_flip_the_flag(client, auth):
    client.post("/api/v1/demo/pause", headers=auth("commander"))
    assert client.get("/api/v1/demo/status",
                      headers=auth("commander")).json()["paused"] is True
    client.post("/api/v1/demo/resume", headers=auth("commander"))
    assert client.get("/api/v1/demo/status",
                      headers=auth("commander")).json()["paused"] is False


def test_manual_tick_pauses_the_loop(client, auth):
    client.post("/api/v1/demo/tick", headers=auth("commander"))
    assert client.get("/api/v1/demo/status",
                      headers=auth("commander")).json()["paused"] is True
    client.post("/api/v1/demo/resume", headers=auth("commander"))


def test_replay_disabled_when_cmapss_is_absent(client, auth, monkeypatch):
    """The engine must report not-running when the telemetry is not loaded.

    This used to depend on `train_FD001.txt` being absent from the repo. That file is
    now staged, so the premise no longer held and the test asserted the opposite of
    what it meant to. It creates the condition instead of waiting for missing data.
    """
    from app.seed.cmapss import cmapss

    monkeypatch.setattr(cmapss, "loaded", False)
    body = client.get("/api/v1/demo/status", headers=auth("commander")).json()
    assert body["running"] is False
    assert body["cmapss_loaded"] is False
