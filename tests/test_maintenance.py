import time
from sqlalchemy import select
from app.maintenance import purge
from app.models import Message


def test_maintenance_purges_old_inactive_conversation(db, scope):
    _, _, conv = scope
    conv.updated = time.time() - 40 * 86400
    db.commit()
    assert purge() == 1
    db.expire_all()
    assert conv.reason == "data_erased"
    assert db.scalar(select(Message)).text == ""
    assert purge() == 0


def test_maintenance_preserves_active_content(db, scope):
    assert purge() == 0
    assert db.scalar(select(Message)).text != ""
