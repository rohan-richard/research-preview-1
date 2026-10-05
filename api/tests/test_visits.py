import uuid
from datetime import timedelta

from app.clock import iso, now
from app.db import SessionLocal
from app.models import Appointment
from tests.conftest import bearer, sign_in


def add_appointment(client, headers, **fields):
    body = {
        "clinician": "Dr. L. Moreno",
        "organization": "Demo Eye Care",
        "kind": "in_person",
        "starts_at": iso(now() + timedelta(days=7)),
        "ends_at": iso(now() + timedelta(days=7, minutes=30)),
        "reason": "Yearly eye exam",
        **fields,
    }
    reply = client.post("/v1/appointments", json=body, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def add_ehr_appointment(user_id: str) -> str:
    with SessionLocal() as db:
        row = Appointment(
            user_id=uuid.UUID(user_id),
            source="ehr",
            clinician="Dr. A. Patel",
            organization="Example Health",
            kind="video",
            status="confirmed",
            starts_at=now() + timedelta(days=2),
            ends_at=now() + timedelta(days=2, minutes=20),
            join_link="https://video.example/abc",
            instructions="Fast for 8 hours",
        )
        db.add(row)
        db.commit()
        return str(row.id)


def add_log(client, headers, **fields):
    body = {"kind": "blood_pressure", "value": {"systolic": 138, "diastolic": 84}, "taken_at": "2026-09-16T12:10:00Z", **fields}
    reply = client.post("/v1/logs", json=body, headers=headers)
    assert reply.status_code == 201, reply.text
    return reply.json()


def ids(reply) -> list[str]:
    return [item["id"] for item in reply.json()["items"]]


def test_add_and_list_appointments_by_status(client, signed_in):
    headers = signed_in.headers
    soon = add_appointment(client, headers)
    assert soon["source"] == "patient" and soon["status"] == "confirmed" and soon["instructions"] is None
    assert soon["prep"] == {"step": "focus", "reviewed": False}
    later = add_appointment(client, headers, starts_at=iso(now() + timedelta(days=30)), ends_at=iso(now() + timedelta(days=30, hours=1)))
    gone = add_appointment(client, headers, starts_at=iso(now() - timedelta(days=10)), ends_at=iso(now() - timedelta(days=10, hours=-1)))

    upcoming = client.get("/v1/appointments", headers=headers).json()
    assert [item["id"] for item in upcoming["items"]] == [soon["id"], later["id"]]
    assert upcoming["next_cursor"] is None
    past = client.get("/v1/appointments?status=past", headers=headers).json()
    assert [item["id"] for item in past["items"]] == [gone["id"]]
    everything = client.get("/v1/appointments?status=all", headers=headers).json()
    assert [item["id"] for item in everything["items"]] == [later["id"], soon["id"], gone["id"]]

    page = client.get("/v1/appointments?limit=1", headers=headers).json()
    assert [item["id"] for item in page["items"]] == [soon["id"]] and page["next_cursor"]
    rest = client.get(f"/v1/appointments?limit=1&cursor={page['next_cursor']}", headers=headers).json()
    assert [item["id"] for item in rest["items"]] == [later["id"]] and rest["next_cursor"] is None
    assert client.get("/v1/appointments?cursor=garbage", headers=headers).status_code == 400
    assert client.get("/v1/appointments?status=soon", headers=headers).status_code == 400


def test_add_appointment_checks_the_body(client, signed_in):
    headers = signed_in.headers
    backwards = client.post(
        "/v1/appointments",
        json={"kind": "video", "starts_at": "2026-10-08T15:30:00Z", "ends_at": "2026-10-08T15:00:00Z"},
        headers=headers,
    )
    assert backwards.status_code == 400 and backwards.json()["error"]["code"] == "invalid_request"
    assert "ends_at" in backwards.json()["error"]["message"]

    naive = client.post("/v1/appointments", json={"kind": "video", "starts_at": "2026-10-08T15:00:00", "ends_at": "2026-10-08T15:30:00"}, headers=headers)
    assert naive.status_code == 400
    bad_link = client.post(
        "/v1/appointments",
        json={"kind": "video", "starts_at": "2026-10-08T15:00:00Z", "ends_at": "2026-10-08T15:30:00Z", "join_link": "zoom"},
        headers=headers,
    )
    assert bad_link.status_code == 400 and "join_link" in bad_link.json()["error"]["message"]
    clinic_only = client.post(
        "/v1/appointments",
        json={"kind": "video", "starts_at": "2026-10-08T15:00:00Z", "ends_at": "2026-10-08T15:30:00Z", "instructions": "Fast"},
        headers=headers,
    )
    assert clinic_only.status_code == 400


def test_patch_and_delete_an_appointment_the_patient_added(client, signed_in):
    headers = signed_in.headers
    appointment = add_appointment(client, headers)
    url = f"/v1/appointments/{appointment['id']}"
    assert client.get(url, headers=headers).json()["clinician"] == "Dr. L. Moreno"

    edited = client.patch(url, json={"clinician": "Dr. P. Shah", "location": None, "status": "pending"}, headers=headers)
    assert edited.status_code == 200, edited.text
    assert edited.json()["clinician"] == "Dr. P. Shah" and edited.json()["status"] == "pending"
    assert edited.json()["reason"] == "Yearly eye exam"

    assert client.patch(url, json={"kind": None}, headers=headers).status_code == 400
    assert client.patch(url, json={"ends_at": appointment["starts_at"]}, headers=headers).status_code == 400
    assert client.patch(url, json={"source": "ehr"}, headers=headers).status_code == 400

    assert client.delete(url, headers=headers).status_code == 204
    assert client.get(url, headers=headers).status_code == 404
    assert client.get(f"{url}/prep", headers=headers).status_code == 404
    assert client.get("/v1/appointments/00000000-0000-0000-0000-000000000000", headers=headers).status_code == 404


def test_ehr_appointments_are_read_only(client, signed_in):
    headers = signed_in.headers
    ehr_id = add_ehr_appointment(signed_in.user["id"])
    url = f"/v1/appointments/{ehr_id}"
    shown = client.get(url, headers=headers).json()
    assert shown["source"] == "ehr" and shown["instructions"] == "Fast for 8 hours" and shown["join_link"] == "https://video.example/abc"

    refused = client.patch(url, json={"clinician": "Someone else"}, headers=headers)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "read_only"
    gone = client.delete(url, headers=headers)
    assert gone.status_code == 403 and gone.json()["error"]["code"] == "read_only"

    # The prep still works for a clinic appointment that arrived without one.
    prep = client.get(f"{url}/prep", headers=headers).json()
    assert prep["appointment_id"] == ehr_id and prep["step"] == "focus" and prep["log_ids"] == []


def test_users_only_see_their_own_appointments(client, fake_provider, signed_in):
    appointment = add_appointment(client, signed_in.headers)
    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com", given_name="Bob").json())
    assert client.get(f"/v1/appointments/{appointment['id']}", headers=other).status_code == 404
    assert client.get("/v1/appointments", headers=other).json()["items"] == []
    assert client.put(f"/v1/appointments/{appointment['id']}/prep", json={"goal": "x"}, headers=other).status_code == 404


def test_prep_is_saved_with_if_match_then_reviewed(client, signed_in):
    headers = signed_in.headers
    appointment = add_appointment(client, headers)
    url = f"/v1/appointments/{appointment['id']}/prep"
    log = add_log(client, headers)

    empty = client.get(url, headers=headers).json()
    assert empty == {
        "appointment_id": appointment["id"],
        "step": "focus",
        "goal": "",
        "changes": "",
        "medication_concerns": "",
        "questions": [],
        "practical_needs": "",
        "log_ids": [],
        "reviewed_at": None,
        "updated_at": empty["updated_at"],
    }
    assert empty["updated_at"].endswith("Z")

    filled = {
        "step": "questions",
        "goal": "Understand my A1c trend",
        "changes": "More leg cramps at night",
        "medication_concerns": "Metformin upsets my stomach",
        "questions": ["Is my A1c going the right way?", "Can the cramps come from my medicine?"],
        "practical_needs": "",
        "log_ids": [log["id"]],
    }
    saved = client.put(url, json=filled, headers={**headers, "If-Match": empty["updated_at"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["goal"] == "Understand my A1c trend" and saved.json()["log_ids"] == [log["id"]]
    assert saved.json()["reviewed_at"] is None
    assert client.get(f"/v1/appointments/{appointment['id']}", headers=headers).json()["prep"] == {"step": "questions", "reviewed": False}

    stale = client.put(url, json={**filled, "goal": "Older edit"}, headers={**headers, "If-Match": '"2020-01-01T00:00:00Z"'})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "edit_conflict"
    assert stale.json()["error"]["prep"]["goal"] == "Understand my A1c trend"
    assert client.get(url, headers=headers).json()["goal"] == "Understand my A1c trend"

    unknown_log = client.put(url, json={**filled, "log_ids": [str(uuid.uuid4())]}, headers=headers)
    assert unknown_log.status_code == 400 and "log_ids" in unknown_log.json()["error"]["message"]
    assert client.put(url, json={**filled, "step": "sleep"}, headers=headers).status_code == 400

    reviewed = client.post(f"{url}/review", headers=headers)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["reviewed_at"].endswith("Z")
    text = reviewed.json()["reviewed_text"]
    assert text.startswith("Goal: Understand my A1c trend\n")
    assert "- Can the cramps come from my medicine?" in text
    assert "blood pressure on 2026-09-16T12:10:00Z: systolic 138, diastolic 84" in text
    assert client.get(url, headers=headers).json()["reviewed_at"] == reviewed.json()["reviewed_at"]
    assert client.get(f"/v1/appointments/{appointment['id']}", headers=headers).json()["prep"]["reviewed"] is True

    # A review does not move updated_at, so the last If-Match still works.
    again = client.put(url, json={**filled, "goal": "A new goal"}, headers={**headers, "If-Match": saved.json()["updated_at"]})
    assert again.status_code == 200, again.text
    assert again.json()["reviewed_at"] is None

    client.patch(f"/v1/appointments/{appointment['id']}", json={"status": "cancelled"}, headers=headers)
    assert client.put(url, json=filled, headers=headers).status_code == 404
    assert client.post(f"{url}/review", headers=headers).status_code == 404


def test_a_new_time_or_a_changed_log_clears_the_review(client, signed_in):
    headers = signed_in.headers
    appointment = add_appointment(client, headers)
    appointment_url = f"/v1/appointments/{appointment['id']}"
    prep_url = f"{appointment_url}/prep"
    log = add_log(client, headers)
    other_log = add_log(client, headers, kind="weight", value={"kg": 81.4})
    assert client.put(prep_url, json={"goal": "Ask about cramps", "log_ids": [log["id"]]}, headers=headers).status_code == 200

    def review():
        assert client.post(f"{prep_url}/review", headers=headers).status_code == 200
        assert client.get(prep_url, headers=headers).json()["reviewed_at"] is not None

    def reviewed() -> bool:
        return client.get(appointment_url, headers=headers).json()["prep"]["reviewed"]

    review()
    assert client.patch(appointment_url, json={"clinician": "Dr. P. Shah"}, headers=headers).status_code == 200
    assert reviewed() is True
    moved = {"starts_at": iso(now() + timedelta(days=8)), "ends_at": iso(now() + timedelta(days=8, minutes=30))}
    assert client.patch(appointment_url, json=moved, headers=headers).status_code == 200
    assert reviewed() is False

    review()
    assert client.patch(f"/v1/logs/{other_log['id']}", json={"value": {"kg": 80}}, headers=headers).status_code == 200
    assert reviewed() is True
    assert client.patch(f"/v1/logs/{log['id']}", json={"value": {"systolic": 134, "diastolic": 84}}, headers=headers).status_code == 200
    assert reviewed() is False

    review()
    assert client.delete(f"/v1/logs/{log['id']}", headers=headers).status_code == 204
    assert reviewed() is False
    assert client.get(prep_url, headers=headers).json()["log_ids"] == []

    review()
    assert client.post(f"/v1/logs/{log['id']}/restore", headers=headers).status_code == 200
    assert reviewed() is False
    assert client.get(prep_url, headers=headers).json()["log_ids"] == [log["id"]]


def test_guide_items_list_filter_edit_and_delete(client, signed_in):
    headers = signed_in.headers
    appointment = add_appointment(client, headers)
    question = client.post(
        "/v1/guide-items",
        json={"kind": "question", "text": "Can the cramps come from my medicine?", "added_from": "From your leg-cramp log, Sep 22"},
        headers=headers,
    )
    assert question.status_code == 201, question.text
    assert question.json() == {
        "id": question.json()["id"],
        "kind": "question",
        "text": "Can the cramps come from my medicine?",
        "added_from": "From your leg-cramp log, Sep 22",
        "appointment_id": None,
        "resolved": False,
    }
    observation = client.post(
        "/v1/guide-items", json={"kind": "observation", "text": "Dizzy after standing", "appointment_id": appointment["id"]}, headers=headers
    ).json()
    assert observation["appointment_id"] == appointment["id"]

    assert client.post("/v1/guide-items", json={"kind": "rant", "text": "x"}, headers=headers).status_code == 400
    assert client.post("/v1/guide-items", json={"kind": "question", "text": ""}, headers=headers).status_code == 400
    unknown = client.post("/v1/guide-items", json={"kind": "question", "text": "x", "appointment_id": str(uuid.uuid4())}, headers=headers)
    assert unknown.status_code == 404

    assert ids(client.get("/v1/guide-items", headers=headers)) == [observation["id"], question.json()["id"]]
    assert ids(client.get(f"/v1/guide-items?appointment_id={appointment['id']}", headers=headers)) == [observation["id"]]

    done = client.patch(f"/v1/guide-items/{question.json()['id']}", json={"resolved": True, "text": "Answered: yes"}, headers=headers)
    assert done.status_code == 200 and done.json()["resolved"] is True and done.json()["text"] == "Answered: yes"
    assert ids(client.get("/v1/guide-items", headers=headers)) == [observation["id"]]
    assert ids(client.get("/v1/guide-items?resolved=true", headers=headers)) == [question.json()["id"]]
    assert ids(client.get("/v1/guide-items?resolved=all", headers=headers)) == [observation["id"], question.json()["id"]]

    page = client.get("/v1/guide-items?resolved=all&limit=1", headers=headers).json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    rest = client.get(f"/v1/guide-items?resolved=all&limit=1&cursor={page['next_cursor']}", headers=headers).json()
    assert [item["id"] for item in rest["items"]] == [question.json()["id"]] and rest["next_cursor"] is None

    detached = client.patch(f"/v1/guide-items/{observation['id']}", json={"appointment_id": None}, headers=headers)
    assert detached.json()["appointment_id"] is None
    assert client.patch(f"/v1/guide-items/{observation['id']}", json={"appointment_id": str(uuid.uuid4())}, headers=headers).status_code == 404

    assert client.delete(f"/v1/guide-items/{observation['id']}", headers=headers).status_code == 204
    assert client.patch(f"/v1/guide-items/{observation['id']}", json={"resolved": True}, headers=headers).status_code == 404
    assert client.delete(f"/v1/guide-items/{observation['id']}", headers=headers).status_code == 404


def test_deleting_an_appointment_keeps_guide_items_but_detaches_them(client, signed_in):
    headers = signed_in.headers
    appointment = add_appointment(client, headers)
    item = client.post("/v1/guide-items", json={"kind": "question", "text": "x", "appointment_id": appointment["id"]}, headers=headers).json()
    assert client.delete(f"/v1/appointments/{appointment['id']}", headers=headers).status_code == 204
    (left,) = client.get("/v1/guide-items", headers=headers).json()["items"]
    assert left["id"] == item["id"] and left["appointment_id"] is None
