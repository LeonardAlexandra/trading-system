# Phase1.1 D4 工程级校验证据包

**模块**: D4 - 恢复失败 → 返回标准 diff 测试（B1 负向链路）  
**依据**: 《Phase1.1 开发交付包》D4、B1 条款  
**日期**: 2026-02-05  

---

## 0. D4 条款对齐表

| Clause ID | Phase1.1 原文条款（保持原语义） | 对条款的理解（1 句话） |
|----------|----------------------------------|------------------------|
| D4-01 | 强校验未通过时返回 400，且响应体包含符合“diff 标准公式”的结构化 diff | 必须走真实 B1 路由，返回 status=400、body 为结构化 diff JSON |
| D4-02 | 响应体包含 diff，且字段与 B1 文档一致、可解析 | diff 顶层 code/checks/snapshot 必须存在，checks 项含 field/expected/actual/pass；禁止纯文本 |
| D4-03 | 测试必须覆盖至少一种强校验失败场景；diff 结构必须与 B1 文档一致 | 构造强校验必然失败场景（如 RUNNING → state_is_paused 失败），断言 diff.checks 至少 1 个失败项 |
| D4-04 | 不依赖真实生产数据；使用 fixture 或 mock 构造失败条件 | 使用 fixture/测试 DB 插入 RUNNING 状态，不依赖生产 |

---

## 1. 目标校验矩阵（逐条覆盖 D4 Clause）

| Clause ID | Phase1.1 条款摘要 | 测试位置（文件:行号） | 校验方式（assert / 请求） | 结果 |
|----------|-------------------|------------------------|----------------------------|------|
| D4-01 | 强校验失败返回 400 + 结构化 diff | test_resume_fail_diff.py:95-98, 147-148 | TestClient POST /strategy/{id}/resume → assert status_code==400, body 为 response.json() | 通过 |
| D4-02 | diff 字段与 B1 一致、可解析 | test_resume_fail_diff.py:100-128, 152-168 | assert code/checks/snapshot 存在；checks 项含 field/expected/actual/pass；snapshot 为 dict | 通过 |
| D4-03 | 至少一种强校验失败场景，diff.checks 至少 1 失败项 | test_resume_fail_diff.py fixture + 95-118 | 插入 status=RUNNING → state_is_paused 失败；assert len([c for c in checks if not c['pass']]) >= 1 | 通过 |
| D4-04 | fixture 构造失败条件 | resume_fail_fixtures.py + test_resume_fail_diff.py fixture | strategy_id + status=RUNNING，文件 DB，不依赖生产 | 通过 |

---

## 2. 关键测试快照（Code Snapshot）

### 2.1 构造强校验必然失败场景（fixture）

**文件**: `tests/fixtures/resume_fail_fixtures.py`

- `strategy_id_for_resume_fail()` → `"D4_RESUME_FAIL_STRAT"`
- `status_that_fails_resume_check()` → `STATUS_RUNNING`（使 state_is_paused 期望 True、实际 False）

**文件**: `tests/integration/test_resume_fail_diff.py` fixture `d4_resume_fail_setup`

- 文件 DB + monkeypatch DATABASE_URL、LOG_DIR
- create_app() 后，同一 DB 上 async session 插入 `strategy_runtime_state(strategy_id, status=RUNNING)`
- yield (app, strategy_id)

### 2.2 触发真实 B1 路由并断言 400 + diff

```python
with TestClient(app) as client:
    response = client.post(f"/strategy/{strategy_id}/resume")

assert response.status_code == 400
body = response.json()  # 禁止纯文本
assert "code" in body and body["code"] == "RESUME_CHECK_FAILED"
assert "checks" in body and isinstance(body["checks"], list)
assert len([c for c in body["checks"] if c.get("pass") is False]) >= 1
assert "snapshot" in body and isinstance(body["snapshot"], dict)
for c in body["checks"]:
    assert all(k in c for k in ("field", "expected", "actual", "pass"))
```

### 2.3 失败语义（非 400 / 非 JSON / 缺字段 / checks 全通过 → 测试失败）

- `test_d4_resume_fail_diff_structure_no_plain_text` 中显式 `pytest.fail(...)`，不吞 assertion。

---

## 3. 测试与实跑输出（原始证据）

### 3.1 仅跑 D4 测试文件

```bash
cd trading_system && python -m pytest tests/integration/test_resume_fail_diff.py -v --tb=short
```

```
============================= test session starts ==============================
platform darwin -- Python 3.13.11, pytest-9.0.2, pluggy-1.5.0
...
collected 2 items

tests/integration/test_resume_fail_diff.py::test_d4_resume_fail_returns_400_and_structured_diff PASSED [ 50%]
tests/integration/test_resume_fail_diff.py::test_d4_resume_fail_diff_structure_no_plain_text PASSED [100%]

============================== 2 passed in 0.37s ===============================
```

### 3.2 pytest -q（全量）

```bash
python -m pytest -q
```

```
........................................................................ [ 35%]
........................................................................ [ 71%]
..........................................................               [100%]
202 passed in 8.11s
```

### 3.3 pytest -q tests/integration/test_resume_fail_diff.py

```bash
python -m pytest -q tests/integration/test_resume_fail_diff.py
```

```
..                                                                        [100%]
2 passed in 0.37s
```

---

## 4. 回归与不变式声明

| 问题 | 结论 | 依据 |
|------|------|------|
| 是否走真实 B1 路由？ | **是** | TestClient(app).post("/strategy/{id}/resume")，未直接调用 resume_strategy |
| 强校验失败是否返回 400？ | **是** | assert response.status_code == 400 |
| 响应体是否为结构化 diff（非纯文本）？ | **是** | response.json()，assert code/checks/snapshot 及 checks 项结构 |
| diff.checks 是否至少 1 个失败项？ | **是** | assert len([c for c in checks if c.get("pass") is False]) >= 1 |
| diff.snapshot 是否可解析？ | **是** | assert isinstance(body["snapshot"], dict) |
| 是否未测恢复成功/挂起链路？ | **是** | 仅构造 RUNNING 触发 state_is_paused 失败，不测 D5/D3 |

---

## 5. 变更清单（Change Manifest）

| 文件 | 变更类型 | 说明 | 对应 Clause |
|------|----------|------|-------------|
| tests/fixtures/resume_fail_fixtures.py | 新增 | 强校验必然失败场景：strategy_id、status=RUNNING | D4-03, D4-04 |
| tests/integration/test_resume_fail_diff.py | 新增 | D4 负向集成测试：真实 B1 路由、400 + diff 结构与 diff.checks 至少 1 失败项、禁止纯文本 | D4-01～D4-04 |
| docs/Phase1.1_D4_工程级校验证据包.md | 新增 | D4 工程级校验证据包（本文件） | 验收输入 |

**未修改生产代码**：仅测试与 fixtures，未改动 B1 路由或 strategy_manager。

---

## 6. 放行自检

- [x] D4 所有 Clause 在校验矩阵中逐条覆盖  
- [x] 走真实 B1 路由 POST /strategy/{id}/resume  
- [x] 强校验失败返回 400，body 为结构化 diff JSON（禁止纯文本）  
- [x] diff 顶层 code/checks/snapshot 及 checks 项 field/expected/actual/pass 符合 B1 文档  
- [x] diff.checks 至少 1 个失败项；若有 snapshot 可解析  
- [x] 失败语义明确：非 400/非 JSON/缺字段/checks 全通过则测试失败，不吞 assertion  
- [x] 工程级校验证据包完整、可复现  

**结论**：D4 满足《Phase1.1 开发交付包》与模块任务约定，可放行。
