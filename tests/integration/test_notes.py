import asyncio
import hashlib

import psycopg
import pytest

from tests.conftest import Database
from tests.helpers import api, assert_field_error, assert_problem

pytestmark = pytest.mark.anyio


async def test_creating_returns_the_note_with_etag_and_location(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await user.request("POST", "/v1/notes", json={"title": "  First  ", "body": "x"})
    assert response.status_code == 201
    note = response.json()
    assert set(note) == {"id", "title", "body", "version", "createdAt", "updatedAt"}
    assert (note["title"], note["version"]) == ("First", 1)
    assert response.headers["etag"] == '"1"'
    assert response.headers["location"] == f"/v1/notes/{note['id']}"


async def test_creating_requires_authentication(database: Database) -> None:
    async with api(database) as client:
        response = await client.http.post("/v1/notes", json={"title": "x"})
    assert_problem(response, 401, "unauthorized")


@pytest.mark.parametrize(
    ("label", "body", "field"),
    [
        ("a blank title", {"title": "   "}, "title"),
        ("a long title", {"title": "x" * 201}, "title"),
        ("a long body", {"title": "x", "body": "y" * 10_001}, "body"),
        ("a missing title", {"body": "y"}, "title"),
        ("an unknown field", {"title": "x", "ownerId": "usr_1"}, "ownerId"),
        ("a NUL character in the title", {"title": "a\u0000b"}, "title"),
        ("a NUL character in the body", {"title": "x", "body": "a\u0000b"}, "body"),
    ],
)
async def test_creating_rejects_invalid_input(
    database: Database, label: str, body: dict[str, str], field: str
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await user.request("POST", "/v1/notes", json=body)
    assert_problem(response, 400, "validation-failed")
    assert_field_error(response, field)


async def test_creating_accepts_values_at_the_limits(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await user.request(
            "POST", "/v1/notes", json={"title": "x" * 200, "body": "y" * 10_000}
        )
    assert response.status_code == 201


async def test_listing_pages_through_every_note_exactly_once_newest_first(
    database: Database,
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        created = [(await user.create_note(f"Note {i}"))["id"] for i in range(5)]
        seen, cursor = [], None
        while True:
            params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
            page = (await user.request("GET", "/v1/notes", params=params)).json()
            seen += [note["id"] for note in page["data"]]
            cursor = page["meta"]["nextCursor"]
            if cursor is None:
                break
    assert seen == list(reversed(created))


async def test_listing_has_no_next_page_when_the_results_fit_exactly(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        for _ in range(2):
            await user.create_note()
        page = (await user.request("GET", "/v1/notes", params={"limit": 2})).json()
    assert (len(page["data"]), page["meta"]["nextCursor"]) == (2, None)


async def test_listing_defaults_to_20_and_returns_an_empty_list(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await user.request("GET", "/v1/notes")
    assert response.json() == {"data": [], "meta": {"limit": 20, "nextCursor": None}}


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("limit=101", "limit"),
        ("limit=0", "limit"),
        ("limit=abc", "limit"),
        ("cursor=bad", "cursor"),
    ],
)
async def test_listing_rejects_bad_parameters(database: Database, query: str, field: str) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await user.request("GET", f"/v1/notes?{query}")
    assert_problem(response, 400, "validation-failed")
    assert_field_error(response, field)


async def test_listing_accepts_the_maximum_limit(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await user.request("GET", "/v1/notes?limit=100")
    assert response.json()["meta"]["limit"] == 100


async def test_hides_another_users_note_everywhere(database: Database) -> None:
    async with api(database) as client:
        owner, intruder = await client.sign_up(), await client.sign_up()
        note = await owner.create_note("Private")
        path = f"/v1/notes/{note['id']}"
        for method, kwargs in (
            ("GET", {}),
            ("PATCH", {"json": {"title": "Mine"}, "headers": {"If-Match": '"1"'}}),
            ("DELETE", {}),
        ):
            assert_problem(await intruder.request(method, path, **kwargs), 404, "not-found")
        listed = (await intruder.request("GET", "/v1/notes")).json()
        assert listed["data"] == []
        assert (await owner.request("GET", path)).json()["title"] == "Private"


@pytest.mark.parametrize("note_id", ["note_00000000000000000000000000000000", "usr_1", "junk"])
async def test_reading_returns_404_for_an_unknown_note(database: Database, note_id: str) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await user.request("GET", f"/v1/notes/{note_id}")
    assert_problem(response, 404, "not-found")


async def test_reading_returns_the_etag(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        note = await user.create_note()
        response = await user.request("GET", f"/v1/notes/{note['id']}")
    assert response.headers["etag"] == '"1"'


async def test_deletes_a_note_once(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        note = await user.create_note()
        path = f"/v1/notes/{note['id']}"
        assert (await user.request("DELETE", path)).status_code == 204
        assert_problem(await user.request("DELETE", path), 404, "not-found")


async def test_updating_changes_only_the_given_fields_and_bumps_the_version(
    database: Database,
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        note = await user.create_note("Old", "Keep me")
        response = await user.request(
            "PATCH", f"/v1/notes/{note['id']}", json={"title": " New "}, headers={"If-Match": '"1"'}
        )
    assert response.status_code == 200
    updated = response.json()
    assert (updated["title"], updated["body"], updated["version"]) == ("New", "Keep me", 2)
    assert response.headers["etag"] == '"2"'
    assert updated["updatedAt"] >= note["updatedAt"]


async def test_updating_allows_an_empty_body(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        note = await user.create_note("T", "Text")
        response = await user.request(
            "PATCH", f"/v1/notes/{note['id']}", json={"body": ""}, headers={"If-Match": '"1"'}
        )
    assert response.json()["body"] == ""


async def test_updating_requires_if_match(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        note = await user.create_note()
        response = await user.request("PATCH", f"/v1/notes/{note['id']}", json={"title": "x"})
    assert_problem(response, 428, "precondition-required")


@pytest.mark.parametrize("if_match", ['"9"', "nonsense", '"99999999999999999999"', '"1" x'])
async def test_updating_rejects_a_stale_or_bad_if_match(database: Database, if_match: str) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        note = await user.create_note()
        response = await user.request(
            "PATCH", f"/v1/notes/{note['id']}", json={"title": "x"}, headers={"If-Match": if_match}
        )
    assert_problem(response, 412, "version-mismatch")


async def test_updating_lets_only_one_of_two_concurrent_updates_win(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        note = await user.create_note()
        responses = await asyncio.gather(
            *(
                user.request(
                    "PATCH",
                    f"/v1/notes/{note['id']}",
                    json={"title": title},
                    headers={"If-Match": '"1"'},
                )
                for title in ("A", "B")
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 412]


@pytest.mark.parametrize(("body", "field"), [({}, ""), ({"title": "   "}, "title")])
async def test_updating_rejects_an_empty_patch_and_a_blank_title(
    database: Database, body: dict[str, str], field: str
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        note = await user.create_note()
        response = await user.request(
            "PATCH", f"/v1/notes/{note['id']}", json=body, headers={"If-Match": '"1"'}
        )
    assert_problem(response, 400, "validation-failed")
    assert_field_error(response, field)


async def test_updating_returns_404_for_an_unknown_note(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await user.request(
            "PATCH",
            "/v1/notes/note_00000000000000000000000000000000",
            json={"title": "x"},
            headers={"If-Match": '"1"'},
        )
    assert_problem(response, 404, "not-found")


async def test_idempotency_returns_the_original_note_on_replay(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        headers = {"Idempotency-Key": "abc"}
        first = await user.request("POST", "/v1/notes", json={"title": "Once"}, headers=headers)
        again = await user.request("POST", "/v1/notes", json={"title": "Once"}, headers=headers)
        listed = (await user.request("GET", "/v1/notes")).json()["data"]
    assert again.status_code == 201
    assert again.json() == first.json()
    assert again.headers["idempotency-replayed"] == "true"
    assert "idempotency-replayed" not in first.headers
    assert len(listed) == 1


async def test_idempotency_creates_one_note_from_concurrent_requests(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        responses = await asyncio.gather(
            *(
                user.request(
                    "POST", "/v1/notes", json={"title": "Race"}, headers={"Idempotency-Key": "race"}
                )
                for _ in range(5)
            )
        )
        listed = (await user.request("GET", "/v1/notes")).json()["data"]
    assert {response.status_code for response in responses} == {201}
    assert len({response.json()["id"] for response in responses}) == 1
    assert len(listed) == 1


async def test_idempotency_rejects_a_reused_key_with_a_different_body(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        headers = {"Idempotency-Key": "same"}
        await user.request("POST", "/v1/notes", json={"title": "One"}, headers=headers)
        response = await user.request("POST", "/v1/notes", json={"title": "Two"}, headers=headers)
    assert_problem(response, 422, "idempotency-key-reused")


async def test_idempotency_never_replays_another_users_note(database: Database) -> None:
    async with api(database) as client:
        first, second = await client.sign_up(), await client.sign_up()
        headers = {"Idempotency-Key": "shared"}
        mine = await first.request("POST", "/v1/notes", json={"title": "X"}, headers=headers)
        theirs = await second.request("POST", "/v1/notes", json={"title": "X"}, headers=headers)
        retried = await first.request("POST", "/v1/notes", json={"title": "X"}, headers=headers)
    assert mine.json()["id"] != theirs.json()["id"]
    assert "idempotency-replayed" not in theirs.headers
    assert retried.json()["id"] == mine.json()["id"]


async def test_idempotency_creates_a_new_note_each_time_without_a_key(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        for _ in range(2):
            await user.create_note("Same")
        listed = (await user.request("GET", "/v1/notes")).json()["data"]
    assert len(listed) == 2


async def test_idempotency_treats_an_expired_key_as_new(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        headers = {"Idempotency-Key": "expiring"}
        first = await user.request("POST", "/v1/notes", json={"title": "A"}, headers=headers)
        await owner.execute(
            "update idempotency_keys set expires_at = now() - interval '1 second' where key = %s",
            ["expiring"],
        )
        same_body = await user.request("POST", "/v1/notes", json={"title": "A"}, headers=headers)
        other_body = await user.request("POST", "/v1/notes", json={"title": "B"}, headers=headers)
        listed = (await user.request("GET", "/v1/notes")).json()["data"]
    assert same_body.status_code == 201
    assert "idempotency-replayed" not in same_body.headers
    assert same_body.json()["id"] != first.json()["id"]
    assert_problem(other_body, 422, "idempotency-key-reused")
    assert len(listed) == 2


async def test_idempotency_never_replays_another_endpoints_response(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        await owner.execute(
            "insert into idempotency_keys (user_id, endpoint, key, request_hash, response_body, "
            "expires_at) select id, 'POST /v1/projects', 'shared', 'other', '{\"id\": \"prj_1\"}', "
            "now() + interval '1 hour' from users where email = %s",
            [user.email],
        )
        headers = {"Idempotency-Key": "shared"}
        created = await user.request("POST", "/v1/notes", json={"title": "X"}, headers=headers)
        retried = await user.request("POST", "/v1/notes", json={"title": "X"}, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["id"].startswith("note_")
    assert "idempotency-replayed" not in created.headers
    assert retried.json()["id"] == created.json()["id"]


@pytest.mark.parametrize("if_match", ["*", ' "1" ', '"7", "1"'])
async def test_updating_accepts_any_matching_strong_etag_or_a_star(
    database: Database, if_match: str
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        note = await user.create_note()
        response = await user.request(
            "PATCH", f"/v1/notes/{note['id']}", json={"title": "x"}, headers={"If-Match": if_match}
        )
    assert response.status_code == 200, response.text
    assert response.headers["etag"] == '"2"'


async def test_updating_with_a_star_still_hides_another_users_note(database: Database) -> None:
    async with api(database) as client:
        owner, other = await client.sign_up(), await client.sign_up()
        note = await owner.create_note()
        response = await other.request(
            "PATCH", f"/v1/notes/{note['id']}", json={"title": "x"}, headers={"If-Match": "*"}
        )
    assert_problem(response, 404, "not-found")


@pytest.mark.parametrize("if_match", ['W/"1"', 'W/"1", W/"2"'])
async def test_updating_never_matches_a_weak_etag_and_says_why(
    database: Database, if_match: str
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        note = await user.create_note()
        response = await user.request(
            "PATCH", f"/v1/notes/{note['id']}", json={"title": "x"}, headers={"If-Match": if_match}
        )
    body = assert_problem(response, 412, "version-mismatch")
    assert body["detail"] == (
        f"If-Match {if_match} has only weak ETags, which never match. Send the strong ETag "
        'from your last read, such as "3".'
    )


async def test_idempotency_fingerprints_the_whole_body_in_any_key_order(database: Database) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        headers = {"Idempotency-Key": "fingerprint", "Content-Type": "application/json"}
        first = await user.request(
            "POST", "/v1/notes", content=b'{"title": "T", "body": "B"}', headers=headers
        )
        reordered = await user.request(
            "POST", "/v1/notes", content=b'{"body":"B","title":"T"}', headers=headers
        )
        changed_body = await user.request(
            "POST", "/v1/notes", content=b'{"title": "T", "body": "C"}', headers=headers
        )
    assert first.status_code == 201
    assert reordered.headers["idempotency-replayed"] == "true"
    assert reordered.json()["id"] == first.json()["id"]
    assert_problem(changed_body, 422, "idempotency-key-reused")


async def test_idempotency_stores_a_fingerprint_of_method_path_and_canonical_body(
    database: Database, owner: psycopg.AsyncConnection
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        await user.request(
            "POST", "/v1/notes", json={"title": "T"}, headers={"Idempotency-Key": "stored"}
        )
    row = await (
        await owner.execute("select request_hash from idempotency_keys where key = 'stored'")
    ).fetchone()
    expected = hashlib.sha256(b'POST /v1/notes\n{"body":"","title":"T"}').hexdigest()
    assert row == (expected,)


async def test_creating_reports_a_body_that_is_not_an_object_with_an_empty_field(
    database: Database,
) -> None:
    async with api(database) as client:
        user = await client.sign_up()
        response = await user.request("POST", "/v1/notes", json=["not", "an", "object"])
    assert_problem(response, 400, "validation-failed")
    assert_field_error(response, "")
