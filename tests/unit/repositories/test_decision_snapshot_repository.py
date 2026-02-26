"""
Phase1.2 C1：DecisionSnapshotRepository 单元测试（仅 insert + select，无 update/delete）
"""
from datetime import datetime, timezone
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.database.connection import Base
from src.models.decision_snapshot import DecisionSnapshot
from src.repositories.decision_snapshot_repository import DecisionSnapshotRepository


@pytest.fixture
async def c1_session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_and_get_by_decision_id(c1_session_factory):
    """正常路径：save 后 get_by_decision_id 返回完整四块。"""
    async with c1_session_factory() as session:
        repo = DecisionSnapshotRepository(session)
        snapshot = DecisionSnapshot(
            decision_id="dec-001",
            strategy_id="strat-1",
            signal_state={"symbol": "BTCUSDT", "side": "BUY"},
            position_state={},
            risk_check_result={"allowed": True},
            decision_result={"decision_id": "dec-001", "symbol": "BTCUSDT"},
        )
        await repo.save(snapshot)
        await session.commit()
    async with c1_session_factory() as session:
        repo = DecisionSnapshotRepository(session)
        row = await repo.get_by_decision_id("dec-001")
    assert row is not None
    assert row.decision_id == "dec-001"
    assert row.strategy_id == "strat-1"
    assert row.signal_state == {"symbol": "BTCUSDT", "side": "BUY"}
    assert row.position_state == {}
    assert row.risk_check_result == {"allowed": True}
    assert row.decision_result == {"decision_id": "dec-001", "symbol": "BTCUSDT"}


@pytest.mark.asyncio
async def test_list_by_strategy_time(c1_session_factory):
    """按 strategy_id + 时间范围返回快照列表。"""
    async with c1_session_factory() as session:
        repo = DecisionSnapshotRepository(session)
        for i in range(3):
            snap = DecisionSnapshot(
                decision_id=f"dec-list-{i}",
                strategy_id="strat-1",
                signal_state={},
                position_state={},
                risk_check_result={},
                decision_result={},
            )
            await repo.save(snap)
        await session.commit()
    async with c1_session_factory() as session:
        repo = DecisionSnapshotRepository(session)
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        end = datetime(2030, 1, 1, tzinfo=timezone.utc)
        rows = await repo.list_by_strategy_time("strat-1", start, end, limit=10, offset=0)
    assert len(rows) == 3
    ids = {r.decision_id for r in rows}
    assert "dec-list-0" in ids and "dec-list-1" in ids and "dec-list-2" in ids


@pytest.mark.asyncio
async def test_repository_has_no_update_or_delete():
    """不可变性：Repository 无 update/delete 方法（代码层面证明）。"""
    assert not hasattr(DecisionSnapshotRepository, "update")
    assert not hasattr(DecisionSnapshotRepository, "delete")
    assert not hasattr(DecisionSnapshotRepository, "overwrite")
