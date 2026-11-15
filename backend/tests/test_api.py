import uuid


async def test_auth_basics(make_client, admin):
    anon = await make_client()
    assert (await anon.get("/api/auth/me")).status_code == 401
    assert (await anon.get("/api/auth/config")).json()["open_signup"] is False
    r = await anon.post("/api/auth/register", json={"username": "xx1", "email": "x1@example.com", "password": "password123"})
    assert r.status_code == 403
    bad = await anon.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert bad.status_code == 401
    me = (await admin.get("/api/auth/me")).json()
    assert me["role"] == "admin"
    # refresh issues new cookies
    assert (await admin.post("/api/auth/refresh")).status_code == 200


async def test_open_signup_toggle(make_client, admin):
    await admin.patch("/api/admin/settings", json={"open_signup": True})
    anon = await make_client()
    r = await anon.post("/api/auth/register", json={"username": "selfreg", "email": "selfreg@example.com", "password": "password123"})
    assert r.status_code == 201
    assert (await anon.get("/api/auth/me")).json()["username"] == "selfreg"
    await admin.patch("/api/admin/settings", json={"open_signup": False})


async def test_admin_user_management(make_client, admin):
    r = await admin.post("/api/admin/users", json={"username": "bob", "email": "bob@example.com", "password": "bob-password"})
    assert r.status_code == 201, r.text
    bob = await make_client("bob", "bob-password")
    assert (await bob.get("/api/admin/users")).status_code == 403
    uid = r.json()["id"]
    await admin.patch(f"/api/admin/users/{uid}", json={"is_active": False})
    assert (await bob.get("/api/auth/me")).status_code == 401


async def test_models_visible_only_when_enabled(make_client, admin, enabled_model):
    r = await admin.post("/api/admin/users", json={"username": "carol", "email": "carol@example.com", "password": "carol-password"})
    carol = await make_client("carol", "carol-password")
    models = (await carol.get("/api/models")).json()
    assert [m["id"] for m in models] == [enabled_model["id"]]
    assert models[0]["is_default"] is True


async def test_chat_flow_memory_and_kv_cache(make_client, admin, enabled_model, sse):
    await admin.post("/api/admin/users", json={"username": "dave", "email": "dave@example.com", "password": "dave-password"})
    dave = await make_client("dave", "dave-password")
    conv = (await dave.post("/api/conversations", json={})).json()
    cid = conv["id"]

    r = await dave.post(f"/api/conversations/{cid}/messages", json={"content": "Hello there, my name is Dave"})
    assert r.status_code == 200
    events = sse(r.text)
    kinds = [e[0] for e in events]
    assert kinds[0] == "meta" and "token" in kinds and kinds[-1] == "done"
    done = events[-1][1]
    assert done["message"]["status"] == "complete" and done["message"]["content"]
    assert done["stats"]["used_kv_cache"] is False

    # auto title (long-poll)
    t = (await dave.get(f"/api/conversations/{cid}/title", params={"wait": 10})).json()
    assert t["title"]

    # second turn: the title job ran in between and invalidated the KV cache -> replay
    r = await dave.post(f"/api/conversations/{cid}/messages", json={"content": "What is my name?"})
    done = sse(r.text)[-1][1]
    assert done["message"]["status"] == "complete"
    # third turn continues the hot conversation -> KV-cache fast path
    r = await dave.post(f"/api/conversations/{cid}/messages", json={"content": "And again?"})
    done = sse(r.text)[-1][1]
    assert done["stats"]["used_kv_cache"] is True

    detail = (await dave.get(f"/api/conversations/{cid}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] * 3
    assert detail["generating"] is False

    # regenerate replaces the last answer and replays (no KV)
    r = await dave.post(f"/api/conversations/{cid}/regenerate", json={})
    events = sse(r.text)
    assert events[0][1]["removed_message_id"] == detail["messages"][-1]["id"]
    assert events[-1][1]["stats"]["used_kv_cache"] is False

    # edit the first user message -> history truncated after it
    first_user = detail["messages"][0]["id"]
    r = await dave.post(f"/api/conversations/{cid}/messages/{first_user}/edit", json={"content": "Hi, I'm David"})
    assert sse(r.text)[-1][0] == "done"
    detail = (await dave.get(f"/api/conversations/{cid}")).json()
    assert len(detail["messages"]) == 2 and detail["messages"][0]["content"] == "Hi, I'm David"

    # list + search
    lst = (await dave.get("/api/conversations")).json()
    assert any(c["id"] == cid for c in lst)
    assert any(c["id"] == cid for c in (await dave.get("/api/conversations", params={"q": "david"})).json())

    # another user cannot see it
    await admin.post("/api/admin/users", json={"username": "eve", "email": "eve@example.com", "password": "eve-password"})
    eve = await make_client("eve", "eve-password")
    assert (await eve.get(f"/api/conversations/{cid}")).status_code == 404
    assert (await eve.post(f"/api/conversations/{cid}/messages", json={"content": "x"})).status_code == 404

    # rename / pin / delete
    r = await dave.patch(f"/api/conversations/{cid}", json={"title": "Renamed", "pinned": True})
    assert r.json()["title"] == "Renamed" and r.json()["pinned"] is True
    assert (await dave.delete(f"/api/conversations/{cid}")).status_code == 204
    assert (await dave.get(f"/api/conversations/{cid}")).status_code == 404


async def test_rolling_summary_kicks_in(make_client, admin, enabled_model, sse):
    await admin.patch(f"/api/admin/models/{enabled_model['id']}", json={"max_context_len": 512, "max_new_tokens": 64})
    try:
        conv = (await admin.post("/api/conversations", json={})).json()
        cid = conv["id"]
        saw_summarizing = False
        for i in range(6):
            r = await admin.post(f"/api/conversations/{cid}/messages", json={"content": f"Message {i}: " + "lorem ipsum " * 25})
            events = sse(r.text)
            saw_summarizing |= any(e[0] == "summarizing" for e in events)
            assert events[-1][0] == "done", events[-1]
        detail = (await admin.get(f"/api/conversations/{cid}")).json()
        assert saw_summarizing
        assert detail["summary"] and detail["summary_upto_seq"] > 0
    finally:
        await admin.patch(f"/api/admin/models/{enabled_model['id']}", json={"max_context_len": 4096, "max_new_tokens": 2048})


async def test_missing_conversation_and_bad_model(admin, enabled_model):
    assert (await admin.get(f"/api/conversations/{uuid.uuid4()}")).status_code == 404
    r = await admin.post("/api/conversations", json={"model_id": 99999})
    assert r.status_code == 400


async def test_openai_compat_with_api_key(make_client, admin, enabled_model):
    key = (await admin.post("/api/keys", json={"name": "cli"})).json()["key"]
    anon = await make_client()
    h = {"Authorization": f"Bearer {key}"}
    models = (await anon.get("/v1/models", headers=h)).json()
    assert models["data"][0]["id"] == enabled_model["filename"]
    r = await anon.post("/v1/chat/completions", headers=h, json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"]
    r = await anon.post("/v1/chat/completions", headers=h, json={"messages": [{"role": "user", "content": "hi"}], "stream": True})
    assert r.text.strip().endswith("data: [DONE]")
    bad = await anon.get("/v1/models", headers={"Authorization": "Bearer rk-wrong"})
    assert bad.status_code == 401


async def test_remove_missing_models(make_client, admin, enabled_model):
    from tests.conftest import MODELS

    files = [MODELS / f"llama-3.2-1b-gone-{i}.rkllm" for i in range(3)]
    for f in files:
        f.write_bytes(b"\0" * 512)
    await admin.post("/api/admin/models/rescan")
    models = {m["filename"]: m for m in (await admin.get("/api/admin/models")).json()}
    gone = [models[f.name] for f in files]
    assert (await admin.patch(f"/api/admin/models/{gone[0]['id']}", json={"enabled": True})).status_code == 200
    conv = (await admin.post("/api/conversations", json={"model_id": gone[0]["id"]})).json()
    assert conv["model_id"] == gone[0]["id"]

    # a model whose file still exists can't be removed
    assert (await admin.delete(f"/api/admin/models/{gone[0]['id']}")).status_code == 409
    # nor by a normal user
    await admin.post("/api/admin/users", json={"username": "carol", "email": "carol@example.com", "password": "carol-password"})
    carol = await make_client("carol", "carol-password")
    assert (await carol.delete(f"/api/admin/models/{gone[0]['id']}")).status_code == 403

    for f in files:
        f.unlink()
    r = (await admin.post("/api/admin/models/rescan")).json()
    assert r["missing"] >= 3
    statuses = {m["id"]: m["status"] for m in (await admin.get("/api/admin/models")).json()}
    assert all(statuses[m["id"]] == "missing" for m in gone)

    # remove one, then the rest in bulk
    assert (await admin.delete(f"/api/admin/models/{gone[0]['id']}")).status_code == 204
    assert (await admin.delete(f"/api/admin/models/{gone[0]['id']}")).status_code == 404
    assert (await admin.get(f"/api/conversations/{conv['id']}")).json()["model_id"] is None
    r = await admin.delete("/api/admin/models")
    assert r.status_code == 200 and r.json()["removed"] == 2
    left = (await admin.get("/api/admin/models")).json()
    assert not [m for m in left if m["status"] == "missing"]
    assert any(m["id"] == enabled_model["id"] for m in left)  # existing models untouched
