"""Only admins choose models; everyone else always gets the instance default."""


async def test_only_admins_choose_models(make_client, admin, enabled_model, sse):
    models = (await admin.get("/api/admin/models")).json()
    gemma = next(m for m in models if m["filename"].startswith("gemma"))
    assert (await admin.patch(f"/api/admin/models/{gemma['id']}", json={"enabled": True})).status_code == 200
    try:
        await admin.post("/api/admin/users", json={"username": "frank", "email": "frank@example.com",
                                                   "password": "frank-password"})
        frank = await make_client("frank", "frank-password")

        # a requested model is ignored: the conversation uses the instance default
        conv = (await frank.post("/api/conversations", json={"model_id": gemma["id"]})).json()
        assert conv["model_id"] == enabled_model["id"]
        r = await frank.post(f"/api/conversations/{conv['id']}/messages",
                             json={"content": "hi", "model_id": gemma["id"]})
        events = sse(r.text)
        assert events[0][1]["model"]["id"] == enabled_model["id"] and events[-1][0] == "done"

        # switching the conversation's model is refused
        r = await frank.patch(f"/api/conversations/{conv['id']}", json={"model_id": gemma["id"]})
        assert r.status_code == 403

        # a personal default model is not stored
        me = (await frank.patch("/api/auth/me", json={"settings": {"default_model_id": gemma["id"], "theme": "dark"}})).json()
        assert "default_model_id" not in me["settings"] and me["settings"]["theme"] == "dark"

        # OpenAI API: a non-admin key gets the default whatever model it names
        key = (await frank.post("/api/keys", json={"name": "cli"})).json()["key"]
        anon = await make_client()
        h = {"Authorization": f"Bearer {key}"}
        r = await anon.post("/v1/chat/completions", headers=h,
                            json={"model": gemma["filename"], "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 200 and r.json()["model"] == enabled_model["filename"]

        # admins can still pick another model
        conv = (await admin.post("/api/conversations", json={"model_id": gemma["id"]})).json()
        assert conv["model_id"] == gemma["id"]
        r = await admin.patch(f"/api/conversations/{conv['id']}", json={"model_id": enabled_model["id"]})
        assert r.status_code == 200 and r.json()["model_id"] == enabled_model["id"]
        akey = (await admin.post("/api/keys", json={"name": "admin-cli"})).json()["key"]
        r = await anon.post("/v1/chat/completions", headers={"Authorization": f"Bearer {akey}"},
                            json={"model": gemma["filename"], "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 200 and r.json()["model"] == gemma["filename"]
    finally:
        await admin.patch(f"/api/admin/models/{gemma['id']}", json={"enabled": False})
