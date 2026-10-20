"""secretbox: authenticated encryption for users.totp_secret at rest."""
import os
import sys
import tempfile

import pytest

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DXMAP_DB_PATH", _TMP.name)
os.environ.setdefault("DXMAP_ENV", "dev")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import db  # noqa: E402
import secretbox  # noqa: E402

db.init_db()


def test_roundtrip():
    tok = secretbox.seal("JBSWY3DPEHPK3PXP")
    assert tok.startswith("v1:") and "JBSWY3DPEHPK3PXP" not in tok
    assert secretbox.open_(tok) == "JBSWY3DPEHPK3PXP"
    assert secretbox.seal("x") != secretbox.seal("x")  # fresh nonce


def test_tamper_raises():
    tok = secretbox.seal("JBSWY3DPEHPK3PXP")
    body = tok[3:]
    flipped = ("A" if body[20] != "A" else "B")
    bad = "v1:" + body[:20] + flipped + body[21:]
    with pytest.raises(ValueError):
        secretbox.open_(bad)
    with pytest.raises(ValueError):
        secretbox.open_("v1:!!!")


def test_legacy_plaintext_passes():
    assert secretbox.open_("JBSWY3DPEHPK3PXP") == "JBSWY3DPEHPK3PXP"


def test_prod_without_token_raises(monkeypatch):
    monkeypatch.setenv("DXMAP_ENV", "prod")
    monkeypatch.delenv("DXMAP_SERVICE_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        secretbox.seal("x")


def test_db_column_is_sealed():
    uid = db.create_user("totp-box@example.com", "pw-long-enough-123", "NONE")
    assert uid is not None
    db.set_totp_pending(uid, "JBSWY3DPEHPK3PXP")
    with db._conn() as conn:
        raw = conn.execute("SELECT totp_secret FROM users WHERE id = ?", (uid,)).fetchone()[0]
    assert raw.startswith("v1:")
    assert db.get_totp(uid)["totp_secret"] == "JBSWY3DPEHPK3PXP"


def test_unopenable_stored_secret_fails_closed(monkeypatch):
    import sqlite3
    import db, totp
    c = sqlite3.connect(db.DB_PATH)
    c.execute("INSERT OR IGNORE INTO users (email,password_hash,role,created_at) VALUES ('sb@e.org','x$y','ADMIN',1)")
    uid = c.execute("SELECT id FROM users WHERE email='sb@e.org'").fetchone()[0]
    c.execute("UPDATE users SET totp_secret='v1:AAAA', totp_enabled=1 WHERE id=?", (uid,))
    c.commit(); c.close()
    state = db.get_totp(uid)
    assert state["totp_secret"] == ""
    assert totp.verify(state["totp_secret"], "123456") is None
