import uuid
from datetime import timedelta

from sqlalchemy import select

from app import content_seed
from app.clock import now
from app.db import SessionLocal
from app.models import ContentItem
from tests.conftest import bearer, sign_in


def seed() -> dict[str, int]:
    with SessionLocal() as db:
        counts = content_seed.load(db)
        db.commit()
    return counts


def add_item(**fields) -> str:
    defaults = {
        "type": "currents",
        "slug": f"piece-{uuid.uuid4().hex[:8]}",
        "data": {"title": "A piece", "kind": "article", "duration_seconds": 20, "media_url": None, "image_url": None, "topics": []},
        "published_at": now(),
    }
    row = ContentItem(**{**defaults, **fields})
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        return str(row.id)


def titles(reply) -> list[str]:
    return [item["title"] for item in reply.json()["items"]]


def test_seed_loader_is_idempotent_and_the_routes_serve_what_it_loaded(client, signed_in):
    first = seed()
    assert first["inserted"] == first["read"] > 0 and first["updated"] == 0
    with SessionLocal() as db:
        ids = set(db.scalars(select(ContentItem.id)))

    again = seed()
    assert again == {"read": first["read"], "inserted": 0, "updated": first["read"]}
    with SessionLocal() as db:
        assert set(db.scalars(select(ContentItem.id))) == ids
        assert db.scalar(select(ContentItem).where(ContentItem.slug == "a1c")).published_at is not None

    headers = signed_in.headers
    currents = client.get("/v1/content/currents?domain=t2d", headers=headers)
    assert currents.status_code == 200, currents.text
    assert "What an A1c of 8.4 actually means" in titles(currents)
    assert "Water is a kidney's best friend" in titles(currents)
    assert "Cold plates, quiet smells" not in titles(currents)

    meals = client.get("/v1/content/library?kind=meal", headers=headers).json()["items"]
    assert {item["kind"] for item in meals} == {"meal"}
    oatmeal = next(item for item in meals if item["id"] == "oatmeal_bowl_blueberries")
    assert oatmeal["name"] == "Oatmeal with blueberries" and oatmeal["facts"]["fiber"] == "high"
    assert oatmeal["image_url"].startswith("https://")

    symptoms = client.get("/v1/content/symptoms?domain=oncology", headers=headers).json()
    assert symptoms["domain"] == "oncology"
    assert symptoms["items"][:2] == [{"name": "Nausea", "body_map": False}, {"name": "Fatigue", "body_map": False}]
    assert symptoms["items"][-1] == {"name": "Poor sleep", "body_map": False}
    assert {"name": "Tingling hands/feet", "body_map": True} in symptoms["items"]

    glossary = client.get("/v1/content/glossary", headers=headers).json()["items"]
    assert glossary[0]["term"] == "A1c" and "three months" in glossary[0]["plain"]
    assert [item["term"] for item in glossary] == sorted(item["term"] for item in glossary)


def test_currents_list_filters_by_domain_and_answers_304_to_the_etag(client, signed_in):
    headers = signed_in.headers
    t2d = add_item(domain="t2d", data={"title": "Salt and blood pressure", "kind": "audio", "duration_seconds": 420, "media_url": "https://cdn.example/salt.m4a", "image_url": "https://cdn.example/salt.jpg", "topics": ["food", "blood_pressure"]})
    add_item(domain="oncology", data={"title": "Cold plates", "kind": "article", "duration_seconds": 20, "media_url": None, "image_url": None, "topics": ["nausea"]})
    everyone = add_item(domain=None, data={"title": "Water", "kind": "article", "duration_seconds": 20, "media_url": None, "image_url": None, "topics": []})

    reply = client.get("/v1/content/currents?domain=t2d", headers=headers)
    assert reply.status_code == 200, reply.text
    assert {item["id"] for item in reply.json()["items"]} == {t2d, everyone}
    salt = next(item for item in reply.json()["items"] if item["id"] == t2d)
    assert salt == {
        "id": t2d,
        "title": "Salt and blood pressure",
        "kind": "audio",
        "duration_seconds": 420,
        "media_url": "https://cdn.example/salt.m4a",
        "image_url": "https://cdn.example/salt.jpg",
        "domain": "t2d",
        "topics": ["food", "blood_pressure"],
    }
    assert len(client.get("/v1/content/currents", headers=headers).json()["items"]) == 3
    assert client.get("/v1/content/currents?domain=procedure", headers=headers).json()["items"][0]["id"] == everyone

    tag = reply.headers["ETag"]
    assert tag.startswith('"') and tag.endswith('"')
    assert client.get("/v1/content/currents?domain=t2d", headers=headers).headers["ETag"] == tag
    cached = client.get("/v1/content/currents?domain=t2d", headers={**headers, "If-None-Match": tag})
    assert cached.status_code == 304 and cached.content == b"" and cached.headers["ETag"] == tag
    assert client.get("/v1/content/currents?domain=t2d", headers={**headers, "If-None-Match": f'W/{tag}, "other"'}).status_code == 304
    assert client.get("/v1/content/currents?domain=oncology", headers={**headers, "If-None-Match": tag}).status_code == 200
    assert client.get("/v1/content/currents?domain=t2d", headers={**headers, "If-None-Match": '"stale"'}).status_code == 200

    # A new version of a piece changes the tag, so a cached client fetches again.
    with SessionLocal() as db:
        row = db.get(ContentItem, uuid.UUID(t2d))
        row.version = 2
        db.commit()
    fresh = client.get("/v1/content/currents?domain=t2d", headers={**headers, "If-None-Match": tag})
    assert fresh.status_code == 200 and fresh.headers["ETag"] != tag


def test_currents_detail_carries_the_users_progress(client, signed_in):
    headers = signed_in.headers
    item = add_item(domain="t2d")
    url = f"/v1/content/currents/{item}"

    shown = client.get(url, headers=headers)
    assert shown.status_code == 200, shown.text
    assert shown.json()["title"] == "A piece"
    assert shown.json()["progress"] == {"position_seconds": None, "completed": False, "updated_at": None}
    tag = shown.headers["ETag"]
    assert client.get(url, headers={**headers, "If-None-Match": tag}).status_code == 304

    saved = client.put(f"{url}/progress", json={"position_seconds": 312, "completed": False}, headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["position_seconds"] == 312 and saved.json()["completed"] is False
    assert saved.json()["updated_at"].endswith("Z")

    after = client.get(url, headers={**headers, "If-None-Match": tag})
    assert after.status_code == 200 and after.json()["progress"] == saved.json()

    done = client.put(f"{url}/progress", json={"position_seconds": 420, "completed": True}, headers=headers).json()
    assert done["completed"] is True and done["position_seconds"] == 420
    assert client.put(f"{url}/progress", json={"position_seconds": 0, "completed": False}, headers=headers).json()["completed"] is False

    assert client.put(f"{url}/progress", json={"position_seconds": -1}, headers=headers).status_code == 400
    assert client.put(f"{url}/progress", json={"position_seconds": 1, "note": "x"}, headers=headers).status_code == 400
    missing = client.get(f"/v1/content/currents/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert client.put(f"/v1/content/currents/{uuid.uuid4()}/progress", json={"position_seconds": 1}, headers=headers).status_code == 404


def test_progress_belongs_to_one_user(client, fake_provider, signed_in):
    item = add_item(domain="t2d")
    url = f"/v1/content/currents/{item}"
    client.put(f"{url}/progress", json={"position_seconds": 100, "completed": True}, headers=signed_in.headers)
    other = bearer(sign_in(client, fake_provider, token="tok-bob", subject="sub-2", email="bob@example.com", given_name="Bob").json())
    assert client.get(url, headers=other).json()["progress"] == {"position_seconds": None, "completed": False, "updated_at": None}


def test_library_filters_by_kind_and_search_text(client, signed_in):
    seed()
    headers = signed_in.headers
    everything = client.get("/v1/content/library", headers=headers).json()["items"]
    assert {item["kind"] for item in everything} == {"meal", "activity"}
    activities = client.get("/v1/content/library?kind=activity", headers=headers).json()["items"]
    assert [item["name"] for item in activities] == sorted(item["name"] for item in activities)
    assert all(item["kind"] == "activity" for item in activities)

    walks = client.get("/v1/content/library?q=walk", headers=headers).json()["items"]
    assert [item["id"] for item in walks] == ["evening_walk"]
    oats = client.get("/v1/content/library?kind=meal&q=OAT", headers=headers).json()["items"]
    assert [item["id"] for item in oats] == ["oatmeal_bowl_blueberries"]
    assert client.get("/v1/content/library?q=zzzz", headers=headers).json()["items"] == []
    assert client.get("/v1/content/library?kind=snack", headers=headers).status_code == 400
    assert client.get("/v1/content/symptoms", headers=headers).status_code == 400


def test_retired_and_unpublished_items_are_hidden(client, signed_in):
    headers = signed_in.headers
    live = add_item(domain="t2d")
    retired = add_item(domain="t2d", retired_at=now() - timedelta(days=1))
    draft = add_item(domain="t2d", published_at=None)
    assert [item["id"] for item in client.get("/v1/content/currents", headers=headers).json()["items"]] == [live]
    assert client.get(f"/v1/content/currents/{retired}", headers=headers).status_code == 404
    assert client.get(f"/v1/content/currents/{draft}", headers=headers).status_code == 404
    assert client.put(f"/v1/content/currents/{retired}/progress", json={"position_seconds": 1}, headers=headers).status_code == 404


def test_content_routes_need_a_token(client):
    for path in ("/v1/content/currents", "/v1/content/library", "/v1/content/symptoms?domain=t2d", "/v1/content/glossary"):
        assert client.get(path).status_code == 401
