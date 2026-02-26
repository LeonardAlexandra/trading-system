"""
Phase1.2 C2：全链路追溯 DTO（蓝本 D.2 写死）

trace_status 枚举：COMPLETE | PARTIAL | NOT_FOUND
missing_nodes 枚举元素：signal, decision, decision_snapshot, execution, trade
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

# 蓝本 D.2 写死
TRACE_STATUS_COMPLETE = "COMPLETE"
TRACE_STATUS_PARTIAL = "PARTIAL"
TRACE_STATUS_FAILED = "FAILED"
TRACE_STATUS_NOT_FOUND = "NOT_FOUND"

MISSING_NODE_SIGNAL = "signal"
MISSING_NODE_DECISION = "decision"
MISSING_NODE_DECISION_SNAPSHOT = "decision_snapshot"
MISSING_NODE_EXECUTION = "execution"
MISSING_NODE_TRADE = "trade"

ALL_MISSING_NODES: List[str] = [
    MISSING_NODE_SIGNAL,
    MISSING_NODE_DECISION,
    MISSING_NODE_DECISION_SNAPSHOT,
    MISSING_NODE_EXECUTION,
    MISSING_NODE_TRADE,
]


@dataclass
class DecisionSummary:
    """列表/回放用决策摘要（C2 基础列表能力，C8 多笔回放+界面）。"""
    decision_id: str
    strategy_id: str
    symbol: str
    side: str
    quantity: Optional[Any] = None
    created_at: Optional[datetime] = None
    status: Optional[str] = None
    signal_id: Optional[str] = None


@dataclass
class TraceSummary:
    """
    C8 多笔回放 list_traces 单条摘要（蓝本 D.9）。
    每条必含 decision_id, trace_status, missing_nodes；PARTIAL 时 missing_nodes 非空；NOT_FOUND 时需明确表达。
    """
    decision_id: str
    trace_status: str  # COMPLETE | PARTIAL | NOT_FOUND
    missing_nodes: List[str]
    strategy_id: Optional[str] = None
    symbol: Optional[str] = None
    created_at: Optional[datetime] = None
    signal_id: Optional[str] = None
    summary: Optional[str] = None  # 蓝本 D.9 可选摘要

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "decision_id": self.decision_id,
            "trace_status": self.trace_status,
            "missing_nodes": self.missing_nodes,
        }
        if self.strategy_id is not None:
            out["strategy_id"] = self.strategy_id
        if self.symbol is not None:
            out["symbol"] = self.symbol
        if self.created_at is not None:
            out["created_at"] = self.created_at.isoformat()
        if self.signal_id is not None:
            out["signal_id"] = self.signal_id
        if self.summary is not None:
            out["summary"] = self.summary
        return out


@dataclass
class TraceResult:
    """
    全链路追溯结果（蓝本 D.2 写死）。
    PARTIAL 时 missing_nodes 必填且非空；NOT_FOUND 时不返回节点或 missing_nodes 为全量五节点。
    """
    trace_status: str  # COMPLETE | PARTIAL | NOT_FOUND
    missing_nodes: List[str]
    missing_reason: Optional[Dict[str, str]] = None
    signal: Optional[Dict[str, Any]] = None
    decision: Optional[Dict[str, Any]] = None
    decision_snapshot: Optional[Dict[str, Any]] = None
    execution: Optional[Dict[str, Any]] = None
    trade: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """供 HTTP 响应 JSON 序列化。"""
        out: Dict[str, Any] = {
            "trace_status": self.trace_status,
            "missing_nodes": self.missing_nodes,
        }
        if self.missing_reason is not None:
            out["missing_reason"] = self.missing_reason
        if self.signal is not None:
            out["signal"] = self.signal
        if self.decision is not None:
            out["decision"] = self.decision
        if self.decision_snapshot is not None:
            out["decision_snapshot"] = self.decision_snapshot
        if self.execution is not None:
            out["execution"] = self.execution
        if self.trade is not None:
            out["trade"] = self.trade
        return out
