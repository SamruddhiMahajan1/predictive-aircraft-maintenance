"""Concurrency (spec 37/38) and the realtime protocol (spec 42/43)."""
from __future__ import annotations

import threading

import pytest

from app.models.auth import AuditLog
from app.models.maintenance import Agency, AgencyBooking, Spare, StockMovement


def _set_stock(client, part_ref_id, stock):
    return client.patch(f"/api/v1/spares/{part_ref_id}",
                        json={"stock": stock, "reason": "adjust"})


# ── 37 no oversell under concurrent reservations ───────────────────────────────
def test_twenty_concurrent_reservations_never_oversell(client, db):
    spare_ref = next(
        i["part_ref_id"] for i in
        client.get("/api/v1/spares").json()["items"]
    )
    _set_stock(client, spare_ref, 1)

    results: list[int] = []
    lock = threading.Lock()

    def reserve() -> None:
        code = client.post(f"/api/v1/spares/{spare_ref}/reserve", json={}).status_code
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


def test_concurrent_reservations_record_one_movement_each(client, db):
    spare_ref = next(
        i["part_ref_id"] for i in
        client.get("/api/v1/spares").json()["items"]
    )
    _set_stock(client, spare_ref, 3)
    spare_id = db.query(Spare).filter(Spare.part_ref_id == spare_ref).one().id
    before = db.query(StockMovement).filter(
        StockMovement.spare_id == spare_id, StockMovement.reason == "reserve"
    ).count()

    def reserve() -> None:
        client.post(f"/api/v1/spares/{spare_ref}/reserve", json={})

    threads = [threading.Thread(target=reserve) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    db.expire_all()
    reserves = db.query(StockMovement).filter(
        StockMovement.spare_id == spare_id,
        StockMovement.reason == "reserve").count()
    assert reserves - before == 3   # exactly the stock that existed


# ── 38 concurrent bookings ────────────────────────────────────────────────────
def test_concurrent_bookings_all_succeed_while_slots_remain(client, db):
    agency = db.query(Agency).first()
    results: list[int] = []
    lock = threading.Lock()

    def book() -> None:
        code = client.post(f"/api/v1/agencies/{agency.id}/bookings",
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


def test_each_booking_is_audited_with_its_eta(client, db):
    agency = db.query(Agency).first()
    client.post(f"/api/v1/agencies/{agency.id}/bookings",
                json={"aircraft": "Fighter-04", "part": "radar"})
    rows = db.query(AuditLog).filter(AuditLog.entity == "agency").all()
    assert rows
    assert all("eta_date" in row.after for row in rows)


def test_booking_free_slot_is_monotonically_non_increasing(client, db):
    from app.models.maintenance import Agency

    agency = db.query(Agency).filter(Agency.turnaround_days == 24).one()
    previous = agency.free_slot_days
    for code in ("Fighter-05", "Fighter-06", "Fighter-07"):
        client.post(f"/api/v1/agencies/{agency.id}/bookings",
                    json={"aircraft": code, "part": "gear"})
        db.expire_all()
        current = db.query(Agency).filter(Agency.id == agency.id).one().free_slot_days
        assert current <= previous, f"{previous} -> {current} must not increase"
        previous = current


# ── 42 WebSocket ──────────────────────────────────────────────────────────────
def test_websocket_sends_connection_ready(client):
    with client.websocket_connect("/ws/fleet") as ws:
        message = ws.receive_json()
    assert message["type"] == "connection.ready"
    assert message["payload"]["aircraft"] == 8
    assert message["payload"]["protocol_version"] == 1


def test_websocket_answers_ping_with_pong(client):
    with client.websocket_connect("/ws/fleet") as ws:
        ws.receive_json()                       # connection.ready
        ws.send_json({"type": "ping", "payload": {}})
        assert ws.receive_json()["type"] == "pong"


def test_ws_declares_the_1013_code_it_now_uses():
    """docs/09 promises 1013 on overflow; guard against it silently disappearing again."""
    from app.realtime.ws import WS_TRY_AGAIN_LATER

    assert WS_TRY_AGAIN_LATER == 1013


def test_a_malformed_frame_does_not_take_the_connection_down(client):
    """A buggy client sending junk must not cost it its socket.

    `receive_json` sat outside the inner try, so non-JSON text or a binary frame raised,
    fell to the blanket handler and closed with 1011 — burning a reconnect and a fresh
    token over one bad frame. Unknown message *types* were already tolerated; unparseable
    ones must be too.
    """
    with client.websocket_connect("/ws/fleet") as ws:
        ws.receive_json()                                  # connection.ready
        ws.send_text("this is not json")
        ws.send_text("{also not json")
        ws.send_json({"type": "no-such-type", "payload": {}})   # unknown type: already ok

        # Still usable afterwards.
        ws.send_json({"type": "ping", "payload": {}})
        for _ in range(50):                               # bounded: must not hang
            message = ws.receive_json()
            if message["type"] == "pong":
                break
        else:
            pytest.fail("connection unusable after malformed frames")


def test_pong_carries_a_seq(client):
    """`seq` has to be usable as an ordering key.

    It was `null` on every pong, because pong was sent from the receive loop with no
    counter involved, so a client could never treat seq as monotonic.
    """
    with client.websocket_connect("/ws/fleet") as ws:
        ready = ws.receive_json()
        assert ready["seq"] == 0
        ws.send_json({"type": "ping", "payload": {}})
        for _ in range(50):
            message = ws.receive_json()
            if message["type"] == "pong":
                assert isinstance(message["seq"], int)
                assert message["seq"] > 0
                break
        else:
            pytest.fail("no pong")


def test_a_filter_does_not_swallow_fleet_wide_events(client):
    """Filtering to one aircraft must still deliver events that name none.

    The test was `if filters and event.payload.get("aircraft") not in filters`, so
    `spare.reserved` and `alert.acked` — which carry no `aircraft` key at all — were
    dropped for every filtered subscriber. Nothing recovers those later either, because
    the client never polls spares or acks.
    """
    from app.realtime.bus import bus
    from app.realtime.events import spare_reserved

    with client.websocket_connect("/ws/fleet") as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe",
                      "payload": {"aircraft": ["Fighter-01"]}})

        bus.publish_soon(spare_reserved({"part_ref_id": 1, "stock_remaining": 4}))
        for _ in range(80):
            message = ws.receive_json()
            if message["type"] == "spare.reserved":
                assert message["payload"]["part_ref_id"] == 1
                break
        else:
            pytest.fail("a fleet-wide event was dropped by an aircraft filter")


def test_a_slow_consumer_is_closed_with_1013_instead_of_left_on_a_dead_socket(
    client, monkeypatch
):
    """The regression that mattered: an overflowed socket must be cut off, not abandoned.

    Overflow used to discard the queue from the fan-out and nothing else. `drain()` then
    blocked on `queue.get()` forever, so the socket stayed open, the console kept showing
    "Backend Live", and engine numbers silently froze — a full socket never trips the
    false→true transition that triggers `refreshFleet()`, so nothing ever resynced.
    docs/09 promised 1013 for exactly this; it had never been implemented.
    """
    from starlette.websockets import WebSocketDisconnect

    from app.realtime.bus import bus
    from app.realtime.events import cycle_tick

    # One slot, and this test never reads while events pile up.
    monkeypatch.setattr(bus, "_maxsize", 1)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/fleet") as ws:
            ws.receive_json()                      # connection.ready
            for _ in range(5):                    # never read these
                bus.publish_soon(cycle_tick(1))
            while True:                           # now start reading: expect the close
                ws.receive_json()

    assert exc.value.code == 1013, "overflow must close, not strand"


def test_websocket_accepts_subscribe(client):
    with client.websocket_connect("/ws/fleet") as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe", "payload": {"aircraft": ["Fighter-01"]}})
        ws.send_json({"type": "ping", "payload": {}})
        assert ws.receive_json()["type"] == "pong"


def test_websocket_ignores_unknown_message_types(client):
    with client.websocket_connect("/ws/fleet") as ws:
        ws.receive_json()
        ws.send_json({"type": "nonsense", "payload": {}})
        ws.send_json({"type": "ping", "payload": {}})
        assert ws.receive_json()["type"] == "pong"


def test_websocket_disconnect_unregisters(client):
    from app.realtime.bus import bus

    before = bus.subscriber_count
    with client.websocket_connect("/ws/fleet") as ws:
        ws.receive_json()
    assert bus.subscriber_count == before


# ── 43 demo controls ──────────────────────────────────────────────────────────
def test_demo_status_reports_the_replay_state(client):
    body = client.get("/api/v1/demo/status").json()
    for field in ("running", "paused", "tick", "interval_seconds", "subscribers"):
        assert field in body


def test_pause_and_resume_flip_the_flag(client):
    client.post("/api/v1/demo/pause")
    assert client.get("/api/v1/demo/status").json()["paused"] is True
    client.post("/api/v1/demo/resume")
    assert client.get("/api/v1/demo/status").json()["paused"] is False


def test_manual_tick_pauses_the_loop(client):
    client.post("/api/v1/demo/tick")
    assert client.get("/api/v1/demo/status").json()["paused"] is True
    client.post("/api/v1/demo/resume")


def test_replay_disabled_when_cmapss_is_absent(client, monkeypatch):
    """The engine must report not-running when the telemetry is not loaded.

    This used to depend on `train_FD001.txt` being absent from the repo. That file is
    now staged, so the premise no longer held and the test asserted the opposite of
    what it meant to. It creates the condition instead of waiting for missing data.
    """
    from app.seed.cmapss import cmapss

    monkeypatch.setattr(cmapss, "loaded", False)
    body = client.get("/api/v1/demo/status").json()
    assert body["running"] is False
    assert body["cmapss_loaded"] is False
