"""SQLite-backed POC accounts and consented subsidiary expert profiles."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from shared.config import get_settings

COMPANIES = {
    "ceat": "CEAT",
    "kec": "KEC International",
    "zensar": "Zensar",
    "harrisons": "Harrisons Malayalam",
}
_SCryptN = 1 << 14


class AccountStore:
    def __init__(self, path: Path | None = None) -> None:
        configured = Path(path or get_settings().neuralmesh_database_path)
        self.path = configured if configured.is_absolute() else Path(__file__).resolve().parents[1] / configured
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    company TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS expert_profiles (
                    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    job_title TEXT NOT NULL,
                    skills_json TEXT NOT NULL,
                    consent INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        company: str,
        expert_opt_in: bool = False,
        expert_title: str = "",
        expert_skills: list[str] | None = None,
    ) -> dict[str, Any]:
        email = email.strip().lower()
        if company not in COMPANIES:
            raise ValueError("Select one of the pilot subsidiaries")
        if expert_opt_in and (not expert_title.strip() or not expert_skills):
            raise ValueError("Expert opt-in requires a role and at least one skill")

        user_id = str(uuid.uuid4())
        salt = secrets.token_bytes(16)
        password_hash = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCryptN, r=8, p=1)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO users(user_id,email,display_name,company,password_salt,password_hash) VALUES(?,?,?,?,?,?)",
                (user_id, email, display_name.strip(), company, salt.hex(), password_hash.hex()),
            )
            if expert_opt_in:
                normalized_skills = sorted({skill.strip() for skill in expert_skills or [] if skill.strip()})
                connection.execute(
                    "INSERT INTO expert_profiles(user_id,job_title,skills_json,consent) VALUES(?,?,?,1)",
                    (user_id, expert_title.strip(), json.dumps(normalized_skills)),
                )
        return self.get_user(user_id)

    def seed_demo_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        company: str,
        expert_title: str | None = None,
        expert_skills: list[str] | None = None,
    ) -> dict[str, Any]:
        """Idempotently upsert a reserved local-only demo account."""
        normalized_email = email.strip().lower()
        if not normalized_email.endswith("@neuralmesh.local"):
            raise ValueError("Demo accounts must use the reserved @neuralmesh.local domain")
        if company not in COMPANIES:
            raise ValueError("Select one of the pilot subsidiaries")

        with self._connect() as connection:
            row = connection.execute("SELECT user_id FROM users WHERE email=?", (normalized_email,)).fetchone()
            user_id = row["user_id"] if row else str(uuid.uuid4())
            salt = secrets.token_bytes(16)
            password_hash = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCryptN, r=8, p=1)
            connection.execute(
                """INSERT INTO users(user_id,email,display_name,company,password_salt,password_hash)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(email) DO UPDATE SET
                     display_name=excluded.display_name,
                     company=excluded.company,
                     password_salt=excluded.password_salt,
                     password_hash=excluded.password_hash""",
                (user_id, normalized_email, display_name.strip(), company, salt.hex(), password_hash.hex()),
            )
            if expert_title:
                skills = sorted({skill.strip() for skill in expert_skills or [] if skill.strip()})
                connection.execute(
                    """INSERT INTO expert_profiles(user_id,job_title,skills_json,consent)
                       VALUES(?,?,?,1)
                       ON CONFLICT(user_id) DO UPDATE SET
                         job_title=excluded.job_title,
                         skills_json=excluded.skills_json,
                         consent=1,
                         updated_at=CURRENT_TIMESTAMP""",
                    (user_id, expert_title.strip(), json.dumps(skills)),
                )
            else:
                connection.execute("DELETE FROM expert_profiles WHERE user_id=?", (user_id,))
        return self.get_user(user_id)

    def authenticate(self, email: str, password: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT u.*, e.job_title, e.skills_json, e.consent
                   FROM users u LEFT JOIN expert_profiles e ON e.user_id=u.user_id
                   WHERE u.email=?""",
                (email.strip().lower(),),
            ).fetchone()
        if row is None:
            hashlib.scrypt(password.encode("utf-8"), salt=b"neuralmesh-poc-salt", n=_SCryptN, r=8, p=1)
            return None
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(row["password_salt"]), n=_SCryptN, r=8, p=1
        ).hex()
        if not secrets.compare_digest(candidate, row["password_hash"]):
            return None
        return self._public_user(row)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT u.*, e.job_title, e.skills_json, e.consent
                   FROM users u LEFT JOIN expert_profiles e ON e.user_id=u.user_id
                   WHERE u.user_id=?""",
                (user_id,),
            ).fetchone()
        return self._public_user(row) if row else None

    @staticmethod
    def _public_user(row: sqlite3.Row) -> dict[str, Any]:
        opted_in = bool(row["consent"]) if "consent" in row.keys() else False
        return {
            "user_id": row["user_id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "company": row["company"],
            "company_name": COMPANIES[row["company"]],
            "roles": ["group_user"],
            "expert_profile": (
                {
                    "job_title": row["job_title"],
                    "skills": json.loads(row["skills_json"]),
                    "consent": opted_in,
                }
                if opted_in
                else None
            ),
        }