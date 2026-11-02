import uuid

import pytest
from fastapi.testclient import TestClient

from api.account_store import AccountStore


def test_account_store_hashes_password_and_keeps_expert_opt_in(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")
    expert = store.create_user(
        email="Expert@Example.test",
        password="correct horse battery",
        display_name="Synthetic Expert",
        company="ceat",
        expert_opt_in=True,
        expert_title="Raw-material quality lead",
        expert_skills=["supplier quality", "natural rubber", "supplier quality"],
    )
    regular = store.create_user(
        email="member@example.test",
        password="another secure password",
        display_name="Group Member",
        company="harrisons",
    )

    assert store.authenticate("EXPERT@example.test", "correct horse battery")["user_id"] == expert["user_id"]
    assert store.authenticate("expert@example.test", "incorrect password") is None
    assert expert["expert_profile"]["consent"] is True
    assert expert["expert_profile"]["skills"] == ["natural rubber", "supplier quality"]
    assert regular["expert_profile"] is None


def test_expert_opt_in_requires_title_and_skills(tmp_path):
    store = AccountStore(tmp_path / "accounts.db")

    with pytest.raises(ValueError, match="requires a role and at least one skill"):
        store.create_user(
            email="person@example.test",
            password="correct horse battery",
            display_name="Person",
            company="kec",
            expert_opt_in=True,
        )


def test_signup_signin_and_me_routes(tmp_path, client: TestClient):
    email = f"poc-{uuid.uuid4().hex}@example.test"
    payload = {
        "email": email,
        "password": "synthetic-data-password",
        "display_name": "POC Member",
        "company": "zensar",
        "expert_opt_in": True,
        "expert_title": "Delivery lead",
        "expert_skills": ["integration", "delivery playbooks"],
    }

    signup = client.post("/api/v1/auth/signup", json=payload)
    assert signup.status_code == 201
    account = signup.json()
    assert account["user"]["company"] == "zensar"
    assert account["user"]["expert_profile"]["consent"] is True

    profile = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {account['access_token']}"},
    )
    assert profile.status_code == 200
    assert profile.json()["user_id"] == account["user"]["user_id"]

    signin = client.post(
        "/api/v1/auth/signin",
        json={"email": email, "password": payload["password"]},
    )
    assert signin.status_code == 200
    assert signin.json()["user"]["expert_profile"]["job_title"] == "Delivery lead"

    bad_password = client.post(
        "/api/v1/auth/signin",
        json={"email": email, "password": "not-the-password"},
    )
    assert bad_password.status_code == 401