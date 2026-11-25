"""V3.2.7.5 D-01：按存档指纹解析后端存档。

覆盖：
* 未见过指纹 → 新建存档并激活；
* 同一指纹再次解析 → 复用原存档（不重复建档）；
* 身份已绑定某存档时，解析即使当前激活的是另一个存档也返回正确存档并切回激活；
* 非 ``si:v1:`` 指纹被拒绝。
"""

from __future__ import annotations

from app.models import FmSave, SaveIdentity

FP_A = "si:v1:file:" + "a" * 64
FP_B = "si:v1:file:" + "b" * 64


def test_resolve_creates_save_for_unseen_fingerprint(client, db, save) -> None:
    response = client.post("/api/v1/saves/resolve", json={"fingerprint": FP_A})
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["save"]["id"] != save.id
    assert body["save"]["is_active"] is True

    db.expire_all()
    assert db.get(FmSave, save.id).is_active is False


def test_resolve_reuses_save_for_known_fingerprint(client, db, save) -> None:
    first = client.post("/api/v1/saves/resolve", json={"fingerprint": FP_A}).json()
    second = client.post("/api/v1/saves/resolve", json={"fingerprint": FP_A, "name": "另一个名字"}).json()

    assert second["created"] is False
    assert second["save"]["id"] == first["save"]["id"]

    db.expire_all()
    assert len(db.query(FmSave).all()) == 2  # fixture save + the new one


def test_resolve_returns_identity_bound_save_and_reactivates(client, db, save) -> None:
    identity_save = FmSave(user_id=save.user_id, name="已绑定的存档", is_active=False)
    other_save = FmSave(user_id=save.user_id, name="当前激活的存档", is_active=True)
    db.add_all([identity_save, other_save])
    db.commit()
    db.add(
        SaveIdentity(
            fm_save_id=identity_save.id,
            identity_fingerprint=FP_B,
            identity_status="verified",
            identity_confidence="high",
            identity_kind="save_file",
        )
    )
    db.commit()

    body = client.post("/api/v1/saves/resolve", json={"fingerprint": FP_B}).json()

    assert body["created"] is False
    assert body["save"]["id"] == identity_save.id
    assert body["save"]["is_active"] is True

    db.expire_all()
    assert db.get(FmSave, identity_save.id).is_active is True
    assert db.get(FmSave, other_save.id).is_active is False


def test_resolve_rejects_non_identity_fingerprint(client) -> None:
    response = client.post("/api/v1/saves/resolve", json={"fingerprint": "not-a-fingerprint"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_fingerprint"
