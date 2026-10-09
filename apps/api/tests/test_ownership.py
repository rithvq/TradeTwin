from sqlalchemy import String, create_engine, delete, select, text, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from tradetwin_security import LEGACY_OWNER, TenantOwned, identity, migrate_ownership


class Base(TenantOwned, DeclarativeBase):
    pass


class Record(Base):
    __tablename__ = "owned_test_records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)


def test_queries_gets_and_bulk_writes_cannot_cross_owners():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    for owner in ["alice", "bob"]:
        token = identity.set({"id": owner})
        try:
            with Session(engine) as db:
                db.add(Record(id=owner, value=owner, owner_id="forged"))
                db.commit()
        finally:
            identity.reset(token)
    token = identity.set({"id": "bob"})
    try:
        with Session(engine) as db:
            assert db.get(Record, "alice") is None
            assert [r.id for r in db.scalars(select(Record))] == ["bob"]
            assert (
                db.execute(
                    update(Record).where(Record.id == "alice").values(value="stolen")
                ).rowcount
                == 0
            )
            assert db.execute(delete(Record).where(Record.id == "alice")).rowcount == 0
            db.commit()
    finally:
        identity.reset(token)
    engine.dispose()


def test_migration_preserves_legacy_rows_without_exposing_them():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE owned_test_records (id VARCHAR PRIMARY KEY, value VARCHAR)"))
        db.execute(text("INSERT INTO owned_test_records VALUES ('old', 'private legacy data')"))
    migrate_ownership(engine, Base.metadata)
    migrate_ownership(engine, Base.metadata)
    token = identity.set({"id": "new-profile"})
    try:
        with Session(engine) as db:
            assert list(db.scalars(select(Record))) == []
    finally:
        identity.reset(token)
    with engine.connect() as db:
        row = db.execute(text("SELECT value, owner_id FROM owned_test_records")).one()
        assert row == ("private legacy data", LEGACY_OWNER)
    engine.dispose()
