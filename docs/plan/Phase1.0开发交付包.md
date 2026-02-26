# Phase 1.0 开发交付包

**版本**: v1.3.1  
**创建日期**: 2026-01-26  
**最后修订**: 2026-01-26  
**基于**: MVP实现计划 v1.2.5 + 模块接口与边界说明书 v1.0

**v1.2.1 修订说明**:
- 修正 stub：移除 StrategyManager 残留引用
- 修正 ExecutionEngine 事务边界：改为两段式幂等（事务A占位→下单→事务B落库）
- 统一 decision_order_map 字段语义：local_order_id（本地订单号）、exchange_order_id（交易所订单号）

**v1.2.2 修订说明**:
- 修正数据库 Session 管理：改为 SessionFactory + 每请求/每任务创建 session（yield/上下文）
- 修正 PositionManager 接口：新增 get_all_positions(strategy_id) 方法
- 统一验签与测试：集成测试使用固定 secret 计算真实 HMAC 签名
- 明确 ExecutionEngine 执行语义：Phase 1.0 paper 模式为"下单即成交"，create_order 返回 filled+trade
- Dependencies 容器字段显式化：明确声明所有会被引用的字段

**v1.2.3 修订说明**:
- 修正 main.py 的 stub 缩进/try-except 结构：确保链路（parser→executor→risk→execution→return）在同一 try 内
- 修正 main.py 的依赖导入：明确导入并使用 get_db_session 与 get_dependencies_with_session
- 清理 dependencies.py 中 get_dependencies_with_session() 的重复代码块
- 修正 test_happy_path.py：补齐 import json，确保 HMAC 计算不报错

**v1.2.4 修订说明**:
- 统一 get_db_session 的来源：明确只允许一个定义位置（放在 src.app.dependencies），修正 main.py 的 import
- 统一 SessionFactory 初始化与存放：lifespan 初始化的工厂通过 set_session_factory 写入 dependencies 模块级变量，get_db_session 使用该变量
- 修正集成测试验签的稳定性：使用固定 separators/sort_keys 的 json.dumps 生成 payload bytes，用 data=payload 发送并设置 Content-Type header

**v1.2.5 修订说明**:
- 统一 get_db_session 的语义与使用方式：明确为 @asynccontextmanager 异步上下文管理器，用于 async with，不是 FastAPI Depends
- 处理 get_dependencies(config) 的"半初始化风险"：删除或明确标注弃用，只保留 get_dependencies_with_session()
- 简化 get_db_session 内部资源管理：async with 已负责 session 关闭，删除额外 close() 调用
- 补齐 DecisionOrderMap.status 的状态枚举闭环：补充 UNKNOWN 状态
- 收敛订单表命名：从 order 改为 orders，避免关键字冲突

**v1.2.6 修订说明**:
- 修复 Alembic 迁移脚本错误：orders 表已改名，但 create_index 仍引用 'order'，统一改为 'orders'
- 裁决 dedup_signal.processed 字段语义：删除 processed 字段，去重只依赖 signal_id PRIMARY KEY
- 将 AsyncSessionFactory 的类型标注改为 Optional[...]，避免类型不严谨

**v1.2.7 修订说明**:
- PR2：将 orders 表相关索引名称从 idx_order_* 统一改为 idx_orders_*（表名已为 orders，索引名保持一致）
- PR5/PR13：补充并写死验签实现约束：SignalReceiver.receive() 必须用 payload_bytes = await request.body() 获取原始 body bytes，并基于该 bytes 调用 TradingViewAdapter.validate_signature(...)；禁止基于 request.json() 二次序列化后再验签
- 统一 ExchangeAdapter 构造函数签名与 dependencies.py 的调用方式；统一 Trade.is_simulated 在 paper 模式下的语义说明（写死为 False）

**v1.2.8 修订说明**:
- 修复 Alembic 迁移脚本中 orders 表的索引名称：将 idx_order_* 全部改为 idx_orders_*，保持与 v1.2.7 修订说明/PR2 验收条目一致

**v1.2.9 修订说明**:
- 修复 PR3 中 get_db_session 伪代码：补充 set_session_factory() 初始化说明，明确 @asynccontextmanager 语义，删除所有 Depends/yield dependency 风格示例
- 全文统一命名：确保表名为 orders、索引名为 idx_orders_*，所有相关引用保持一致

**v1.3.0 修订说明**:
- 集成测试验签配置闭环：明确 test 环境下应用加载的 tradingview.webhook_secret 必须与测试里用于计算 HMAC 的 secret 完全一致（推荐在 pytest fixture 里 monkeypatch TV_WEBHOOK_SECRET=test_webhook_secret 或提供 config.test.yaml），写入 PR13 验收/测试说明
- ExecutionEngine 异常状态必须落库：写死约束——当标记 decision_order_map.status 为 TIMEOUT/FAILED/UNKNOWN 时，必须保证该更新不会被 request-level rollback 回滚（例如异常分支显式 commit 后再抛异常，或使用独立 session 小事务），写入 PR11 事务策略与 PR14 恢复说明
- 补充说明 BaseRepository 接口示例仅示意/统一为 async 风格；明确 Phase1 不实现 Shadow 因此 Trade.is_simulated 恒 False；明确 PositionManager.update_from_trade 不得自行开启独立事务

**v1.3.1 修订说明**（最后一次文档修订，消除所有会导致实现/测试稳定跑偏或返工的阻塞项）:
- 写死集成测试的 App 启动时机：禁止在测试模块 import 时直接 from src.app.main import app 并立刻 TestClient(app)；必须使用 create_app() 工厂模式，pytest fixture 中先 monkeypatch.setenv(...)（包括 TV_WEBHOOK_SECRET、DATABASE_URL）再调用 create_app() 再创建 TestClient(app)，明确所有测试配置注入必须发生在 app/lifespan 初始化之前
- 写死集成测试验签 secret 的闭环来源：测试中用于计算 HMAC 的 webhook_secret 必须与应用运行时加载的 TV_WEBHOOK_SECRET 完全一致，给出唯一口径（pytest fixture 中 monkeypatch.setenv("TV_WEBHOOK_SECRET", "test_webhook_secret")），禁止"测试里算一个 secret，应用里读另一个 secret"的隐式配置
- 写死集成测试数据库策略：必须二选一并明确为唯一真理（推荐 SQLite 如 sqlite+aiosqlite:///./test.db，测试启动前自动建表或迁移；或 Docker Postgres fixture 启动、等待 ready、跑迁移），明确测试不依赖本地已有数据库、不依赖人工先跑命令
- 清理依赖注入示例中的错误/残留口径：删除或修正所有 db_session = await get_db_session() 的错误用法；依赖示例中 get_db_session 只能以 async with get_db_session() as session: 的形式出现；Phase1 文档中 StrategyManager 必须完全消失（只保留 StrategyExecutor）；删除重复/冲突的依赖初始化示例，只保留一个权威版本

---

## 一、PR/Commit 粒度任务拆分

### PR1: 项目初始化与基础架构

**目标**: 建立项目骨架、依赖管理、配置模板、基础日志

**涉及模块**: 
- 项目结构
- 配置管理
- 日志系统

**关键接口**: 无（基础设施）

**验收用例**（引用 MVP v1.2.5）:
- [ ] 项目目录结构符合规范
- [ ] 依赖管理文件（pyproject.toml 或 requirements.txt）配置正确
- [ ] 环境变量和配置文件模板准备完成
- [ ] 基础日志系统可以正常工作
- [ ] **数据库 Session 管理**：使用 SessionFactory（async_sessionmaker）模式，不在全局常驻单个 session
- [ ] **每请求创建 session**：通过 `get_db_session()` 上下文管理器，每请求/每任务创建新的 session
- [ ] 可以通过 `uvicorn app.main:app --workers 1` 启动（单实例约束）

**风险点**:
- 依赖版本冲突
- 配置文件格式错误
- 日志配置不当导致性能问题

**交付物**:
- 项目目录结构
- `pyproject.toml` 或 `requirements.txt`
- `.env.example` 和 `config/config.example.yaml`
- `src/utils/logging.py`
- `README.md`（启动说明）

---

### PR2: 数据库模型定义与迁移脚本

**目标**: 定义所有数据表结构，创建 Alembic 迁移脚本

**涉及模块**: 
- TradeRepository
- LogRepository
- 去重表（dedup_signal）
- 幂等映射表（decision_order_map）
- position_snapshot

**关键接口**: 
- SQLAlchemy ORM 模型
- Alembic 迁移脚本

**验收用例**（引用 MVP v1.2.5）:
- [ ] `dedup_signal` 表存在，`signal_id` 为 PRIMARY KEY（唯一约束）
- [ ] `decision_order_map` 表存在，`decision_id` 为 PRIMARY KEY（唯一约束）
- [ ] `decision_order_map.local_order_id` 为可空字段（本地订单号，支持先占位后下单）
- [ ] `decision_order_map.exchange_order_id` 为可空字段（交易所订单号）
- [ ] `decision_order_map` 包含 `status` 和 `reserved_at` 字段（支持占位状态）
- [ ] 字段语义明确：`local_order_id`=本地订单号，`exchange_order_id`=交易所订单号
- [ ] `trade` 表存在，包含所有必要字段
- [ ] `orders` 表存在，包含所有必要字段（表名改为 orders，避免 SQL 关键字冲突）
- [ ] `orders` 表的索引名称统一为 `idx_orders_*`（与表名 orders 保持一致，减少维护歧义）
- [ ] `position_snapshot` 表存在，包含唯一约束（strategy_id, symbol, side）
- [ ] `log` 表存在，支持日志存储
- [ ] 可以通过 `alembic upgrade head` 成功创建所有表
- [ ] 数据库唯一约束正确设置（防止重复插入）

**风险点**:
- 唯一约束设置错误导致去重失效
- 字段类型不匹配（如 DECIMAL 精度）
- 迁移脚本顺序错误

**交付物**:
- `src/models/__init__.py`
- `src/models/trade.py`
- `src/models/order.py`
- `src/models/position_snapshot.py`
- `src/models/dedup_signal.py`
- `src/models/decision_order_map.py`
- `src/models/log.py`
- `alembic/versions/001_initial_schema.py`

---

### PR3: 数据库连接与 Repository 基础层

**目标**: 实现数据库连接池、基础 Repository 抽象类

**涉及模块**: 
- TradeRepository（基础 CRUD）
- LogRepository（基础 CRUD）
- 数据库连接管理

**关键接口**: 
```python
# 数据库连接管理（SessionFactory 模式）
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from contextlib import asynccontextmanager
from typing import Optional

# SessionFactory（全局单例，在 lifespan 中初始化）
AsyncSessionFactory: Optional[async_sessionmaker[AsyncSession]] = None

# 在 lifespan 中调用 set_session_factory() 设置工厂
def set_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    """设置 SessionFactory（由 lifespan 调用，单一权威实现）"""
    global AsyncSessionFactory
    AsyncSessionFactory = factory

# 每请求/每任务创建 session（异步上下文管理器）
@asynccontextmanager
async def get_db_session() -> AsyncSession:
    """
    异步上下文管理器，用于 async with get_db_session() as session:
    
    使用方式：
        async with get_db_session() as session:
            # 使用 session
            ...
        # async with 自动负责 session 的关闭与回收，无需手动调用 close()
    
    注意：
        - 这是 @asynccontextmanager 装饰的异步上下文管理器，不是 FastAPI Depends 的 yield dependency
        - 不能作为 FastAPI Depends 使用，必须在代码中显式使用 async with 语法
        - SessionFactory 必须在应用启动时通过 set_session_factory() 初始化
    """
    if AsyncSessionFactory is None:
        raise RuntimeError("SessionFactory not initialized. Call set_session_factory() in lifespan.")
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        # async with 已负责 session 关闭，无需额外 close()

class BaseRepository:
    """
    Repository 基础抽象类（接口示例仅示意，统一为 async 风格）
    
    注意：
    - 所有方法均为 async 方法
    - 接口示例仅示意，实际实现需根据具体 Repository 调整
    - Phase 1.0 不要求完整实现所有 Repository 接口，仅实现必要方法
    """
    def __init__(self, db_session: AsyncSession)  # 改为 AsyncSession
    async def create(self, entity: Base) -> Base
    async def get_by_id(self, id: str) -> Base | None
    async def update(self, entity: Base) -> Base
    async def delete(self, id: str) -> bool
```

**验收用例**:
- [ ] 数据库连接池配置正确
- [ ] 可以成功连接数据库（PostgreSQL/SQLite）
- [ ] Repository 基础 CRUD 操作可以正常工作
- [ ] 事务管理正确（commit/rollback）
- [ ] 连接池在系统重启后可以自动重连

**风险点**:
- 连接池配置不当导致连接泄漏
- 事务未正确提交导致数据丢失
- 数据库连接字符串配置错误

**交付物**:
- `src/database/__init__.py`
- `src/database/connection.py`
- `src/repositories/base.py`
- `src/repositories/trade.py`（基础 CRUD）
- `src/repositories/log.py`（基础 CRUD）

---

### PR4: TradingViewAdapter 库实现

**目标**: 实现 Webhook 签名验证和数据格式转换库

**涉及模块**: 
- TradingViewAdapter（库，非 HTTP 入口）

**关键接口**: 
```python
class TradingViewAdapter:
    @staticmethod
    def validate_signature(
        payload: bytes, 
        signature: str, 
        secret: str
    ) -> bool
    
    @staticmethod
    def parse_webhook(webhook_data: dict) -> RawSignal
    
    @staticmethod
    def generate_signal_id(webhook_data: dict, secret_salt: str) -> str
```

**验收用例**（引用 MVP v1.2.5）:
- [ ] 能够验证 Webhook 签名（HMAC-SHA256）
- [ ] 签名验证失败时返回 False
- [ ] 能够解析 Webhook JSON 数据
- [ ] **signal_id 生成规范**:
  - 若 webhook payload 中包含 `signal_id`，则直接使用
  - 否则生成稳定 signal_id：`sha256(secret_salt + symbol + action + bar_time + indicator_name [+ price 可选])`
  - 要求：同一事件重放，signal_id 必须一致（可复现）
- [ ] 能够生成 RawSignal 对象（包含 signal_id、received_at 等）
- [ ] 错误处理完善（无效 JSON、缺失字段等）
- [ ] **测试环境验签配置**:
  - 集成测试必须使用固定 secret 计算真实 HMAC 签名（与生产一致）
  - 或明确 test 环境跳过验签（需写清配置开关 `TEST_SKIP_SIGNATURE_VALIDATION=true` 与风险说明）
  - 确保 test_happy_path 与 test_duplicate_signal 都能通过验签进入去重逻辑

**风险点**:
- 签名验证算法错误导致安全漏洞
- signal_id 生成不稳定导致去重失效
- 时区处理错误导致时间戳不准确
- 数据解析失败时未正确处理异常

**交付物**:
- `src/adapters/tradingview.py`
- `tests/adapters/test_tradingview.py`（单元测试，包含 signal_id 生成稳定性测试）

---

### PR5: SignalReceiver HTTP 入口实现

**目标**: 实现 FastAPI Webhook 路由，调用 TradingViewAdapter

**涉及模块**: 
- SignalReceiver（HTTP 入口）

**关键接口**: 
```python
class SignalReceiver:
    def __init__(self, adapter: TradingViewAdapter, webhook_secret: str)
    async def receive(self, request: Request) -> RawSignal
        """
        接收并验证 Webhook 请求
        
        实现约束（必须遵守）：
        1. 必须使用 payload_bytes = await request.body() 获取原始 body bytes
        2. 基于 payload_bytes 调用 TradingViewAdapter.validate_signature(payload_bytes, signature, secret)
        3. 禁止使用 request.json() 后再序列化验签（会导致与集成测试不一致）
        4. 验签通过后，使用 json.loads(payload_bytes) 解析 JSON
        """
```

**验收用例**（引用 MVP v1.2.5）:
- [ ] 能够接收 TradingView Webhook 信号
- [ ] **验签实现约束**：必须使用 `payload_bytes = await request.body()` 获取原始 body bytes，并基于该 bytes 调用 `TradingViewAdapter.validate_signature(payload_bytes, signature, secret)`；禁止基于 `request.json()` 二次序列化后再验签，以确保与集成测试（`data=payload_bytes`）一致
- [ ] 能够验证 Webhook 签名（通过 TradingViewAdapter）
- [ ] 签名验证失败时返回 401
- [ ] 能够调用 TradingViewAdapter 进行数据转换
- [ ] 能够将 RawSignal 传递给 SignalParser（下一步实现）
- [ ] 错误处理完善（返回适当的 HTTP 状态码）

**风险点**:
- HTTP 路由配置错误
- 异步处理不当导致阻塞
- 错误信息泄露敏感信息

**交付物**:
- `src/signal/receiver.py`
- `src/app/main.py`（FastAPI 应用入口）
- `tests/signal/test_receiver.py`

---

### PR6: SignalParser 信号解析与去重

**目标**: 实现信号解析、标准化、数据库去重

**涉及模块**: 
- SignalParser
- DedupSignalRepository

**关键接口**: 
```python
class SignalParser:
    def __init__(self, dedup_repo: DedupSignalRepository)
    async def parse(self, raw_signal: RawSignal) -> StandardizedSignal | None
```

**验收用例**（引用 MVP v1.2.5）:
- [ ] 能够解析 RawSignal，提取标准化字段
- [ ] 能够验证信号格式完整性
- [ ] **信号去重**: 相同 signal_id 永久只处理一次（DB 唯一键保证）
  - 测试：发送相同 webhook payload 3 次（确保 signal_id 一致），验证只生成 1 个交易决策
  - 验收：重复信号被拒绝，记录去重日志，不生成重复订单
  - 验证：signal_id 生成稳定，同一事件重放 signal_id 一致
- [ ] 去重操作记录到数据库（dedup_signal 表）
- [ ] `first_seen_at` 和 `received_at` 仅用于审计，不影响去重判定
- [ ] 能够生成 StandardizedSignal 对象

**风险点**:
- 去重逻辑未使用数据库唯一约束，导致重复处理
- 时间戳解析错误
- 信号格式验证不完整

**交付物**:
- `src/signal/parser.py`
- `src/repositories/dedup_signal.py`
- `tests/signal/test_parser.py`（包含去重测试）

---

### PR7: StrategyExecutor Mock 实现（含单策略路由）

**目标**: 实现最简单的策略逻辑（Mock），生成交易决策；Phase 1.0 为单 Active Strategy，移除 StrategyManager，单策略路由固定在依赖注入层

**涉及模块**: 
- StrategyExecutor（唯一真理版本，Mock 实现）
- 单策略路由逻辑（简化版，不独立模块）

**关键接口**: 
```python
class StrategyExecutor:
    def __init__(self, config: dict)
    async def execute(
        self, 
        signal: StandardizedSignal,
        positions: list[Position],
        market_data: MarketData
    ) -> TradingDecision
```

**验收用例**（引用 MVP v1.2.5）:
- [ ] 策略能够生成交易决策
- [ ] Mock 策略逻辑：收到 BUY 信号 → 买入固定数量
- [ ] Mock 策略逻辑：收到 SELL 信号 → 平仓
- [ ] 能够生成 TradingDecision 对象（包含 decision_id、symbol、side 等）
- [ ] 决策原因记录完整（reason 字段）
- [ ] 单策略路由：Phase 1.0 明确为"单 Active Strategy"，移除 StrategyManager，信号在依赖注入层直接路由到 Executor

**风险点**:
- 决策逻辑错误导致错误交易
- decision_id 生成不唯一

**交付物**:
- `src/strategy/executor.py`（包含单策略路由逻辑）
- `src/strategy/models.py`（TradingDecision）
- `src/strategy/mock_strategy.py`（Mock 策略实现）
- `tests/strategy/test_executor.py`

---

### PR8: ExchangeAdapter 基础实现（Paper Trading）

**目标**: 实现交易所 API 适配器，支持 Paper Trading（前置到 AccountManager/PositionManager/RiskManager 之前，消除依赖倒置）

**涉及模块**: 
- ExchangeAdapter
- MarketDataAdapter

**关键接口**: 
```python
class ExchangeAdapter:
    def __init__(self, exchange_config: dict, product_type: str)
    async def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price_type: str,
        client_order_id: str | None = None
    ) -> ExchangeOrder
    async def get_account_info(self) -> AccountInfo
    async def get_positions(self) -> list[Position]

class MarketDataAdapter:
    async def get_market_data(self, symbol: str) -> MarketData
```

**验收用例**（引用 MVP v1.2.5）:
- [ ] 能够提交订单到交易所（Paper Trading）
- [ ] **Phase 1.0 Paper 模式执行语义**：明确为"下单即成交"
  - `create_order` 返回 `ExchangeOrder`，包含 `status="FILLED"` 和 `filled_trade` 信息
  - 允许 ExecutionEngine 在事务B中直接写入 trade 记录
  - 若未来支持异步成交，则 trade 生成推迟到订单同步阶段
- [ ] 支持 client_order_id（用于幂等性）
- [ ] 能够查询账户信息
- [ ] 能够查询市场数据（价格、订单簿）
- [ ] 错误处理完善（API 超时、网络错误等）

**风险点**:
- API 调用失败时未正确处理
- client_order_id 格式不符合交易所要求
- 超时设置不当

**交付物**:
- `src/adapters/exchange.py`
- `src/adapters/market_data.py`
- `src/adapters/models.py`（ExchangeOrder, MarketData）
- `tests/adapters/test_exchange.py`

---

### PR9: AccountManager 与 PositionManager 基础实现

**目标**: 实现账户信息查询和持仓管理（position_snapshot 投影表）

**涉及模块**: 
- AccountManager（依赖 ExchangeAdapter）
- PositionManager
- PositionSnapshotRepository

**关键接口**: 
```python
class AccountManager:
    def __init__(self, exchange_adapter: ExchangeAdapter)
    async def get_account_info(self) -> AccountInfo

class PositionManager:
    def __init__(
        self, 
        snapshot_repo: PositionSnapshotRepository,
        trade_repo: TradeRepository
    )
    async def get_position(
        self, 
        strategy_id: str, 
        symbol: str, 
        side: str
    ) -> Position | None
    async def get_all_positions(self, strategy_id: str) -> list[Position]  # 新增：获取策略所有持仓
    async def update_from_trade(self, trade: Trade) -> None
        """
        根据成交记录更新持仓（成交驱动更新）
        
        约束：
        - 不得自行开启独立事务，必须使用调用方传入的 session
        - 在 ExecutionEngine 的事务B中调用，共享同一事务上下文
        """
```

**验收用例**（引用 MVP v1.2.5）:
- [ ] 能够查询账户信息（通过 ExchangeAdapter）
- [ ] 能够查询单个持仓（get_position：基于 position_snapshot 投影表，运行时真理源）
- [ ] 能够查询策略所有持仓（get_all_positions(strategy_id)：返回该策略的所有持仓列表）
- [ ] position_snapshot 表有唯一约束（strategy_id, symbol, side）
- [ ] 持仓查询从 position_snapshot 读取，不直接查询交易所

**风险点**:
- position_snapshot 数据不一致
- 账户信息查询失败时未正确处理

**交付物**:
- `src/account/manager.py`
- `src/position/manager.py`
- `src/repositories/position_snapshot.py`
- `tests/account/test_manager.py`
- `tests/position/test_manager.py`

---

### PR10: RiskManager 基础风控实现

**目标**: 实现基础风控检查（单笔风险、账户风险）

**涉及模块**: 
- RiskManager（依赖 PositionManager、AccountManager）

**关键接口**: 
```python
class RiskManager:
    def __init__(
        self, 
        position_manager: PositionManager,
        account_manager: AccountManager,
        config: dict
    )
    async def check(self, decision: TradingDecision) -> RiskCheckResult
```

**验收用例**（引用 MVP v1.2.5）:
- [ ] 风控检查能够通过/拒绝决策
- [ ] 单笔交易风险检查（仓位、资金）
- [ ] 账户级风险检查（总仓位、资金充足性）
- [ ] 风控拒绝时返回拒绝原因
- [ ] 风控检查结果记录到日志

**风险点**:
- 风控规则计算错误
- 风控检查未正确执行导致风险暴露

**交付物**:
- `src/risk/manager.py`
- `src/risk/models.py`（RiskCheckResult）
- `src/risk/rules.py`（风控规则）
- `tests/risk/test_manager.py`

---

### PR11: ExecutionEngine 订单执行引擎

**目标**: 实现订单执行，保证幂等性（decision_id → local_order_id 映射），明确两段式事务边界

**涉及模块**: 
- ExecutionEngine
- DecisionOrderMapRepository
- TradeRepository
- OrderRepository
- PositionManager

**关键接口**: 
```python
class ExecutionEngine:
    def __init__(
        self,
        exchange_adapter: ExchangeAdapter,
        decision_order_repo: DecisionOrderMapRepository,
        trade_repo: TradeRepository,
        order_repo: OrderRepository,
        position_manager: PositionManager
    )
    async def execute(self, decision: TradingDecision) -> ExecutionResult
```

**事务策略（两段式幂等）**:
```python
# 两段式幂等流程：事务A占位 → 交易所下单 → 事务B落库

# === 事务A：幂等占位 ===
BEGIN TRANSACTION A
  # 1. decision_id 幂等抢占（唯一约束，先占位）
  INSERT INTO decision_order_map (
    decision_id, 
    local_order_id,  # 初始为 NULL（本地订单号）
    exchange_order_id,  # 初始为 NULL（交易所订单号）
    status,  # "RESERVED"
    reserved_at
  ) 
  ON CONFLICT (decision_id) DO NOTHING
  
  IF conflict:
    # 查询已存在的记录
    existing = decision_order_repo.get(decision_id)
    IF existing.local_order_id:
      RETURN existing.local_order_id  # 已下单，幂等返回
    ELSE:
      # 占位但未下单，继续执行下单流程
COMMIT TRANSACTION A

# === 交易所下单（不在事务内） ===
# Phase 1.0 Paper 模式：下单即成交，create_order 返回 filled+trade
try:
  order = exchange_adapter.create_order(..., client_order_id=decision_id)
  # order.status = "FILLED"（Paper 模式立即成交）
  # order.filled_trade = Trade(...)（包含成交信息）
except TimeoutError:
  # 交易所超时：标记占位状态为 "TIMEOUT"，可重试
  # 【异常状态必须落库约束】：必须保证该更新不会被 request-level rollback 回滚
  # 方案：使用独立 session 小事务显式 commit，或异常分支显式 commit 后再抛异常
  async with get_db_session() as error_session:
    error_repo = DecisionOrderMapRepository(error_session)
    await error_repo.update(decision_id, status="TIMEOUT")
    await error_session.commit()  # 显式 commit，确保状态落库
  raise
except ExchangeError:
  # 交易所失败：标记占位状态为 "FAILED"
  # 【异常状态必须落库约束】：必须保证该更新不会被 request-level rollback 回滚
  async with get_db_session() as error_session:
    error_repo = DecisionOrderMapRepository(error_session)
    await error_repo.update(decision_id, status="FAILED")
    await error_session.commit()  # 显式 commit，确保状态落库
  raise

# === 事务B：落库并更新映射 ===
BEGIN TRANSACTION B
  # 2. 更新 decision_order_map（填充订单号）
  decision_order_repo.update(
    decision_id, 
    local_order_id=order.order_id,  # 本地订单号
    exchange_order_id=order.exchange_order_id,  # 交易所订单号
    status="FILLED"
  )
  
  # 3. 落库（order, trade, position_snapshot）
  # Phase 1.0 Paper 模式：下单即成交，直接写入 trade
  order_repo.create(order)
  IF order.filled_trade:  # Paper 模式有成交信息
    trade_repo.create(order.filled_trade)
    position_manager.update_from_trade(order.filled_trade)
  # 若未来支持异步成交，则 trade 生成推迟到订单同步阶段
COMMIT TRANSACTION B

# 异常路径：
# - 事务A失败：ROLLBACK，decision_id 未占位，可重试
# - 交易所超时/失败：保留占位记录（status="TIMEOUT"/"FAILED"），可重试
#   【异常状态必须落库约束】：当标记 decision_order_map.status 为 TIMEOUT/FAILED/UNKNOWN 时，
#   必须保证该更新不会被 request-level rollback 回滚（使用独立 session 小事务显式 commit）
# - 事务B失败：ROLLBACK，但占位记录保留，重试时查询到占位但无 local_order_id，继续下单
# - 可恢复策略：超时订单可通过 OrderManager 重试（查询 decision_order_map，发现占位但无 local_order_id，继续下单）
```

**验收用例**（引用 MVP v1.2.5）:
- [ ] 能够提交订单到交易所（Paper Trading）
- [ ] **订单幂等性**: 相同 decision_id 的决策不会重复提交订单
  - 测试：相同 decision_id 的 TradingDecision 提交 2 次
  - 验收：第二次提交被拒绝，返回已存在订单 ID，不重复下单
- [ ] **两段式幂等流程**: 事务A占位 → 交易所下单（不在事务内）→ 事务B落库
  - 测试：事务A占位成功，交易所下单失败，事务B不执行
  - 验收：decision_order_map 插入冲突时，查询已存在记录：
    - 如果 local_order_id 已存在 → 直接返回，不执行下单
    - 如果 local_order_id 为 NULL（占位但未下单）→ 继续执行下单流程
- [ ] **交易所超时 + 重试，不产生重复下单（由 DB 幂等保证）**
  - 测试：模拟交易所超时，重试相同 decision_id
  - 验收：重试时查询 decision_order_map，发现占位记录但 local_order_id 为 NULL，继续下单；如果 local_order_id 已存在，不重复下单
- [ ] **异常恢复**: 交易所超时/失败时，占位记录保留（status="TIMEOUT"/"FAILED"），可重试
- [ ] **异常状态必须落库**: 当标记 decision_order_map.status 为 TIMEOUT/FAILED/UNKNOWN 时，必须保证该更新不会被 request-level rollback 回滚（使用独立 session 小事务显式 commit，或异常分支显式 commit 后再抛异常）
- [ ] 优先使用 client_order_id=decision_id（方案 A）
- [ ] 如果不支持 client_order_id，使用 decision_order_map 表（方案 B）
- [ ] 订单执行结果记录到数据库（orders 表、trade 表，在事务B中）
- [ ] **Phase 1.0 Paper 模式**：下单即成交，create_order 返回 filled+trade，事务B直接写入 trade
- [ ] position_snapshot 在事务B中更新（成交驱动）
- [ ] 执行失败时正确处理错误（标记状态、记录日志）

**风险点**:
- 幂等性未正确实现导致重复下单
- 事务边界不清晰导致数据不一致
- 交易所超时处理不当导致状态混乱
- 订单状态更新不及时

**交付物**:
- `src/execution/engine.py`（包含事务管理，依赖 order_repo）
- `src/repositories/decision_order_map.py`（支持占位和更新）
- `src/execution/models.py`（ExecutionResult）
- `tests/execution/test_engine.py`（包含幂等性测试、事务测试、超时重试测试）

---

### PR12: OrderManager 基础实现（查询、取消、状态同步）

**目标**: 实现订单查询、取消、状态同步（基础版）

**涉及模块**: 
- OrderManager
- OrderRepository

**关键接口**: 
```python
class OrderManager:
    def __init__(
        self,
        exchange_adapter: ExchangeAdapter,
        order_repo: OrderRepository
    )
    async def get_order(self, order_id: str) -> Order | None
    async def cancel_order(self, order_id: str, reason: str) -> bool
    async def sync_order_status(self, order_id: str) -> Order
```

**验收用例**（引用 MVP v1.2.5）:
- [ ] 能够查询订单状态
- [ ] 能够取消未成交订单
- [ ] 订单状态能够实时同步（从交易所 API）
- [ ] 订单状态同步定时任务（进程内调度，如 APScheduler）
- [ ] 改价功能延后（不实现）

**风险点**:
- 订单状态同步不及时
- 取消订单失败时未正确处理

**交付物**:
- `src/execution/order_manager.py`
- `src/repositories/order.py`
- `tests/execution/test_order_manager.py`

---

### PR13: 完整 Happy Path 串联（单策略路由固定）

**目标**: 串联所有模块，实现完整的信号处理流程；集成单策略路由逻辑

**涉及模块**: 
- 所有已实现模块
- 单策略路由逻辑（Phase 1.0 固定单策略，无 StrategyManager）

**关键接口**: 
- 完整的信号处理链路
- 单策略路由（Phase 1.0 明确为"单 Active Strategy"）

**验收用例**（引用 MVP v1.2.5）:
- [ ] **完整流程**: FastAPI webhook → Adapter 验签/转换 → Parser 标准化 → Executor（mock）→ Risk（pass）→ ExecutionEngine → ExchangeAdapter（paper）→ 落库 → 日志
- [ ] 能够接收 TradingView Webhook 信号
- [ ] **验签与测试一致性**：集成测试必须使用固定 secret 计算真实 HMAC 签名（与生产一致），确保 test_happy_path 与 test_duplicate_signal 都能通过验签进入去重逻辑
- [ ] **验签实现约束**：SignalReceiver.receive() 必须用 `payload_bytes = await request.body()` 获取原始 body bytes，并基于该 bytes 调用 `TradingViewAdapter.validate_signature(payload_bytes, signature, secret)`；禁止基于 `request.json()` 二次序列化后再验签，以确保与集成测试（`data=payload_bytes`）一致
- [ ] **集成测试验签配置闭环（唯一口径）**：test 环境下应用加载的 `tradingview.webhook_secret` 必须与测试里用于计算 HMAC 的 secret 完全一致
  - **唯一口径**：在 pytest fixture 里 `monkeypatch.setenv("TV_WEBHOOK_SECRET", "test_webhook_secret")`，确保测试中用于计算 HMAC 的 webhook_secret 与应用运行时加载的 TV_WEBHOOK_SECRET 完全一致
  - **禁止**："测试里算一个 secret，应用里读另一个 secret"的隐式配置
  - 验收：test_happy_path 与 test_duplicate_signal 都能通过验签进入去重逻辑，不出现验签失败
- [ ] **集成测试 App 启动时机（唯一口径）**：禁止在测试模块 import 时直接 `from src.app.main import app` 并立刻 `TestClient(app)`
  - **唯一口径**：必须使用 `create_app()` 工厂模式
  - **流程**：pytest fixture 中先 `monkeypatch.setenv(...)`（包括 `TV_WEBHOOK_SECRET`、`DATABASE_URL`）再调用 `create_app()` 再创建 `TestClient(app)`
  - **约束**：所有测试配置注入必须发生在 app/lifespan 初始化之前
- [ ] **集成测试数据库策略（唯一口径）**：必须二选一并明确为唯一真理
  - **推荐方案**：SQLite（如 `sqlite+aiosqlite:///./test.db`），测试启动前自动建表或迁移
  - **或**：Docker Postgres（fixture 启动、等待 ready、跑迁移）
  - **约束**：测试不依赖本地已有数据库、不依赖人工先跑命令，新机器可直接跑
- [ ] 能够解析信号并路由到策略（单策略路由，直接到 Executor）
- [ ] 策略能够生成交易决策
- [ ] 风控检查能够通过/拒绝决策
- [ ] 能够提交订单到交易所（Paper Trading）
- [ ] **Phase 1.0 Paper 模式执行语义**：下单即成交，create_order 返回 filled+trade，事务B直接写入 trade
- [ ] 能够记录交易到数据库
- [ ] 能够查询持仓和账户信息（使用 get_all_positions(strategy_id)）
- [ ] 能够查看基础日志
- [ ] **数据库 Session 管理**：每请求创建新的 session，不在全局常驻

**风险点**:
- 模块间接口不匹配
- 异步处理错误导致死锁
- 错误处理不完善导致流程中断

**交付物**:
- `src/app/main.py`（完整的 FastAPI 应用）
- `src/app/dependencies.py`（依赖注入，单策略路由固定：signal → executor，无 StrategyManager）
- `tests/integration/test_happy_path.py`（集成测试）

---

### PR14: 异常恢复与错误处理

**目标**: 实现异常恢复机制和错误处理

**涉及模块**: 
- 所有模块的错误处理
- 进程重启恢复

**关键接口**: 
- 错误处理中间件
- 恢复机制

**验收用例**（引用 MVP v1.2.5）:
- [ ] **交易所 API 超时恢复**: 30 秒超时，标记 TIMEOUT，不阻塞后续处理
- [ ] **进程重启恢复**: 重启后能够从数据库恢复策略状态、position_snapshot、未完成订单
- [ ] **重复 Webhook 处理**: 通过 signal_id 去重，重复 Webhook 被拒绝，返回 200 OK
- [ ] **数据库连接中断恢复**: 自动重连机制（重试间隔：5 秒、10 秒、30 秒，最多 3 次）
- [ ] **交易所连接中断恢复**: 连接中断时标记订单为 UNKNOWN，恢复后自动同步
- [ ] **异常状态必须落库（恢复场景）**: 当标记 decision_order_map.status 为 TIMEOUT/FAILED/UNKNOWN 时，必须保证该更新不会被 request-level rollback 回滚（使用独立 session 小事务显式 commit），确保异常状态能够持久化，支持后续恢复流程

**风险点**:
- 恢复机制不完善导致数据丢失
- 错误处理不当导致系统崩溃

**交付物**:
- `src/app/middleware.py`（错误处理中间件）
- `src/utils/recovery.py`（恢复机制）
- `tests/integration/test_recovery.py`

---

### PR15: 日志系统基础实现（文件日志为主）

**目标**: 实现基础日志记录（文件日志为主，关键事件写入数据库）

**涉及模块**: 
- LogRepository（简化版）
- 日志中间件

**关键接口**: 
```python
class LogRepository:
    async def create_log(self, log_entry: LogEntry) -> None  # 仅关键事件
    async def query_logs(
        self,
        start_time: datetime,
        end_time: datetime,
        level: str | None = None
    ) -> list[LogEntry]
```

**日志策略**（Phase 1.0 简化）:
- **文件日志**: 所有日志写入文件（结构化日志，JSON 格式）
- **数据库日志**: 仅关键事件写入数据库（下单、风控拒绝、异常）
- **全量数据库日志**: 推迟到 Phase 1.2+

**验收用例**（引用 MVP v1.2.5）:
- [ ] 能够查看基础日志（文件日志）
- [ ] 所有关键操作都有日志记录（文件）
- [ ] 关键事件写入数据库（下单、风控拒绝、异常）
- [ ] 日志可以按时间、级别查询（文件日志）
- [ ] 日志不包含敏感信息（API Key 等）

**风险点**:
- 日志文件过大导致磁盘空间不足
- 数据库日志写入影响性能（已简化，仅关键事件）

**交付物**:
- `src/repositories/log.py`（简化版，仅关键事件）
- `src/app/middleware.py`（日志中间件）
- `src/utils/logging.py`（日志配置，文件日志为主）

---

### PR16: Docker Compose 单机部署配置

**目标**: 配置 Docker Compose 用于单机/单实例部署

**涉及模块**: 
- 部署配置

**关键接口**: 
- Docker Compose 配置
- 启动脚本

**验收用例**（引用 MVP v1.2.5）:
- [ ] Docker Compose 配置正确（1 app + 1 DB）
- [ ] 可以通过 `docker-compose up` 启动系统
- [ ] 禁止扩容与多实例（配置中明确 workers=1）
- [ ] 环境变量正确传递
- [ ] 数据库初始化脚本执行正确

**风险点**:
- Docker 配置错误导致无法启动
- 环境变量未正确传递

**交付物**:
- `docker-compose.yml`
- `Dockerfile`
- `.dockerignore`
- `scripts/init_db.sh`（数据库初始化）

---

### PR17: 文档与测试完善

**目标**: 完善文档和核心测试（调整测试目标以匹配 MVP 节奏）

**涉及模块**: 
- 所有模块

**关键接口**: 
- 文档
- 测试用例

**验收用例**（调整测试目标）:
- [ ] README.md 包含启动说明
- [ ] API 文档完整（FastAPI 自动生成）
- [ ] **硬性测试目标**（Phase 1.0 必须）:
  - 幂等性测试（signal / decision / order）
  - 异常恢复测试（超时、重启、重复 webhook）
  - 最小集成测试（happy path）
- [ ] **尽力而为**（不作为阻塞条件）:
  - 单元测试覆盖率（尽力而为，不要求 > 80%）
  - 集成测试覆盖完整流程（尽力而为）
- [ ] 部署文档完整

**风险点**:
- 文档不完整导致使用困难
- 核心测试缺失导致关键 bug 未发现

**交付物**:
- `README.md`（完善）
- `docs/API.md`
- `docs/DEPLOYMENT.md`
- 核心测试文件（幂等性、异常恢复、happy path）

---

## 二、Repo 初始化骨架

### 2.1 目录结构

```
trading_system/
├── src/
│   ├── __init__.py
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI 应用入口
│   │   ├── dependencies.py       # 依赖注入
│   │   └── middleware.py         # 中间件（错误处理、日志）
│   ├── signal/
│   │   ├── __init__.py
│   │   ├── receiver.py          # SignalReceiver
│   │   └── parser.py            # SignalParser
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── executor.py          # StrategyExecutor（Phase 1.0 单策略，无 StrategyManager）
│   │   ├── mock_strategy.py     # Mock 策略实现
│   │   └── models.py            # TradingDecision 等
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── manager.py           # RiskManager
│   │   ├── rules.py             # 风控规则
│   │   └── models.py            # RiskCheckResult
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── engine.py            # ExecutionEngine
│   │   └── order_manager.py     # OrderManager
│   ├── position/
│   │   ├── __init__.py
│   │   └── manager.py           # PositionManager
│   ├── account/
│   │   ├── __init__.py
│   │   └── manager.py           # AccountManager
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── tradingview.py       # TradingViewAdapter
│   │   ├── exchange.py          # ExchangeAdapter
│   │   ├── market_data.py       # MarketDataAdapter
│   │   └── models.py            # ExchangeOrder, MarketData 等
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── base.py              # BaseRepository
│   │   ├── trade.py             # TradeRepository
│   │   ├── order.py              # OrderRepository
│   │   ├── position_snapshot.py # PositionSnapshotRepository
│   │   ├── dedup_signal.py      # DedupSignalRepository
│   │   ├── decision_order_map.py # DecisionOrderMapRepository
│   │   └── log.py               # LogRepository
│   ├── models/
│   │   ├── __init__.py
│   │   ├── trade.py             # Trade 模型
│   │   ├── order.py             # Order 模型
│   │   ├── position_snapshot.py # PositionSnapshot 模型
│   │   ├── dedup_signal.py      # DedupSignal 模型
│   │   ├── decision_order_map.py # DecisionOrderMap 模型
│   │   └── log.py               # Log 模型
│   ├── database/
│   │   ├── __init__.py
│   │   └── connection.py       # 数据库连接管理
│   └── utils/
│       ├── __init__.py
│       ├── logging.py           # 日志配置
│       └── config.py            # 配置加载
├── tests/
│   ├── __init__.py
│   ├── unit/
│   │   ├── signal/
│   │   ├── strategy/
│   │   ├── risk/
│   │   ├── execution/
│   │   └── adapters/
│   └── integration/
│       ├── test_happy_path.py
│       └── test_recovery.py
├── alembic/
│   ├── versions/
│   └── env.py
├── config/
│   ├── config.example.yaml
│   └── logging.yaml
├── scripts/
│   ├── init_db.sh
│   └── start.sh
├── .env.example
├── .gitignore
├── pyproject.toml              # 或 requirements.txt
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
└── README.md
```

### 2.2 依赖管理（pyproject.toml）

```toml
[project]
name = "trading-system"
version = "0.1.0"
description = "TradingView Signal Driven Trading System"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.12.0",
    "psycopg2-binary>=2.9.0",  # PostgreSQL
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "ccxt>=4.0.0",  # 交易所 API
    "apscheduler>=3.10.0",  # 进程内调度（禁止 Celery）
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.1.0",
    "black>=23.11.0",
    "ruff>=0.1.0",
    "mypy>=1.7.0",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.uvicorn]
workers = 1  # 单实例约束
```

### 2.3 环境变量模板（.env.example）

```bash
# 数据库配置
DATABASE_URL=postgresql://user:password@localhost:5432/trading_system
# 或开发环境使用 SQLite
# DATABASE_URL=sqlite:///./trading_system.db

# TradingView Webhook
TV_WEBHOOK_SECRET=your_webhook_secret_here

# 交易所配置（Phase 1.0 固定 1 家交易所 + 1 种产品形态）
EXCHANGE_NAME=binance  # 固定值：binance | okx | bybit
EXCHANGE_SANDBOX=true  # true=Paper Trading, false=实盘
EXCHANGE_API_KEY=your_api_key
EXCHANGE_API_SECRET=your_api_secret
PRODUCT_TYPE=spot  # 固定值：spot | perp

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=/var/log/trading_system/app.log
LOG_DATABASE=true

# 应用配置
APP_ENV=development  # development | production
APP_HOST=0.0.0.0
APP_PORT=8000
```

### 2.4 配置文件模板（config/config.example.yaml）

```yaml
# 交易所配置（Phase 1.0 固定）
exchange:
  name: "binance"  # 固定 1 家交易所
  sandbox: true    # true=Paper Trading, false=实盘
  api_key: "${EXCHANGE_API_KEY}"
  api_secret: "${EXCHANGE_API_SECRET}"

product_type: "spot"  # 固定 1 种产品形态，"spot" | "perp" 二选一

# TradingView 配置
tradingview:
  webhook_secret: "${TV_WEBHOOK_SECRET}"

# 策略配置
strategy:
  strategy_id: "MOCK_STRATEGY_V1"
  config:
    max_position_size: 0.1  # 最大仓位（BTC）
    fixed_order_size: 0.01  # Mock 策略固定订单大小

# 风控配置
risk:
  max_single_trade_risk: 0.01  # 单笔最大风险 1%
  max_account_risk: 0.05       # 账户最大风险 5%

# 数据库配置
database:
  url: "${DATABASE_URL}"
  pool_size: 5
  max_overflow: 10
  pool_recycle: 3600

# 日志配置
logging:
  level: "INFO"
  file: "/var/log/trading_system/app.log"
  database: true
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

### 2.5 启动方式

**开发环境**:
```bash
# 1. 安装依赖
pip install -e ".[dev]"

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件

# 3. 初始化数据库
alembic upgrade head

# 4. 启动应用（单实例，workers=1）
uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --workers 1 --reload
```

**生产环境（Docker Compose）**:
```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 文件

# 2. 启动（单机/单实例部署）
docker-compose up -d

# 查看日志
docker-compose logs -f app
```

**Docker Compose 配置（docker-compose.yml）**:
```yaml
version: '3.8'

services:
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: trading_user
      POSTGRES_PASSWORD: trading_password
      POSTGRES_DB: trading_system
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U trading_user"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build: .
    command: uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --workers 1
    environment:
      - DATABASE_URL=postgresql://trading_user:trading_password@db:5432/trading_system
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8000:8000"
    volumes:
      - ./logs:/var/log/trading_system
    restart: unless-stopped

volumes:
  postgres_data:
```

### 2.6 基础日志配置（src/utils/logging.py）

```python
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional

def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    log_to_database: bool = False
) -> None:
    """设置日志配置"""
    # 根日志配置
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # 文件处理器（如果配置）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d"
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    # 数据库日志（如果配置，由 LogRepository 处理）
    if log_to_database:
        # 数据库日志处理器将在 LogRepository 中实现
        pass
```

---

## 三、数据模型 + 迁移方案

### 3.1 数据模型定义

#### 3.1.1 dedup_signal（信号去重表）

```python
# src/models/dedup_signal.py
from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.sql import func
from src.database.connection import Base

class DedupSignal(Base):
    __tablename__ = "dedup_signal"
    
    signal_id = Column(String(100), primary_key=True)  # 唯一键，保证永久去重
    first_seen_at = Column(DateTime(timezone=True), nullable=False)  # 首次接收时间（审计用）
    received_at = Column(DateTime(timezone=True), nullable=False)  # 当前接收时间（审计用）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 唯一约束：signal_id 为 PRIMARY KEY
    # 插入冲突即判定重复
    # 注意：去重只依赖 signal_id PRIMARY KEY，不依赖 processed 字段（已删除）
```

#### 3.1.2 decision_order_map（决策订单映射表）

```python
# src/models/decision_order_map.py
from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from src.database.connection import Base

class DecisionOrderMap(Base):
    __tablename__ = "decision_order_map"
    
    decision_id = Column(String(100), primary_key=True)  # 唯一键，保证幂等
    local_order_id = Column(String(100), nullable=True)  # 本地订单号（可空，支持先占位后下单）
    exchange_order_id = Column(String(100), nullable=True)  # 交易所订单号（可空）
    status = Column(String(20), default="RESERVED")  # "RESERVED" | "FILLED" | "FAILED" | "TIMEOUT" | "UNKNOWN"
    reserved_at = Column(DateTime(timezone=True), server_default=func.now())  # 占位时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 唯一约束：decision_id 为 PRIMARY KEY
    # 保证重试不重复下单
    # 字段语义：
    # - local_order_id: 本地订单号（系统生成的 order_id）
    # - exchange_order_id: 交易所返回的订单号
    # 支持先占位（local_order_id=NULL）后下单（更新 local_order_id）的两段式幂等策略
    # status 状态说明：
    # - RESERVED: 已占位，等待下单
    # - FILLED: 已下单并落库
    # - FAILED: 下单失败
    # - TIMEOUT: 交易所超时
    # - UNKNOWN: 交易所连接中断、下单结果不可确认、系统重启时的中间态
```

#### 3.1.3 trade（交易记录表）

```python
# src/models/trade.py
from sqlalchemy import Column, String, Numeric, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from src.database.connection import Base

class Trade(Base):
    __tablename__ = "trade"
    
    trade_id = Column(String(100), primary_key=True)
    strategy_id = Column(String(50), nullable=False)
    signal_id = Column(String(100), nullable=False)  # 关联信号
    decision_id = Column(String(100), nullable=False)  # 关联决策
    execution_id = Column(String(100), nullable=False)  # 关联执行
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)  # "BUY" | "SELL"
    quantity = Column(Numeric(20, 8), nullable=False)
    price = Column(Numeric(20, 8), nullable=False)
    slippage = Column(Numeric(20, 8), default=0)
    realized_pnl = Column(Numeric(20, 8), default=0)
    executed_at = Column(DateTime(timezone=True), nullable=False)
    is_simulated = Column(Boolean, default=False)  # Shadow 交易标记（Phase 1.0 不实现 Shadow，恒为 False；paper 模式均为 False，实盘 Active 交易也为 False）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 索引
    __table_args__ = (
        {"comment": "交易记录表（Active + Shadow）"}
    )
```

#### 3.1.4 orders（订单表，避免 SQL 关键字冲突）

```python
# src/models/order.py
from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey
from sqlalchemy.sql import func
from src.database.connection import Base

class Order(Base):
    __tablename__ = "orders"  # 改为 orders，避免 SQL 关键字冲突
    
    order_id = Column(String(100), primary_key=True)
    exchange_order_id = Column(String(100))  # 交易所订单 ID
    strategy_id = Column(String(50), nullable=False)
    decision_id = Column(String(100), nullable=False)  # 关联决策（用于幂等）
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)  # "BUY" | "SELL"
    quantity = Column(Numeric(20, 8), nullable=False)
    filled_quantity = Column(Numeric(20, 8), default=0)
    price = Column(Numeric(20, 8))
    status = Column(String(20), nullable=False)  # "PENDING" | "PARTIAL" | "FILLED" | "CANCELLED" | "REJECTED" | "TIMEOUT" | "UNKNOWN"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 索引
    __table_args__ = (
        {"comment": "订单表"}
    )
```

#### 3.1.5 position_snapshot（持仓投影表）

```python
# src/models/position_snapshot.py
from sqlalchemy import Column, String, Numeric, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from src.database.connection import Base

class PositionSnapshot(Base):
    __tablename__ = "position_snapshot"
    
    id = Column(String(100), primary_key=True)
    strategy_id = Column(String(50), nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)  # "long" | "short"
    quantity = Column(Numeric(20, 8), nullable=False)
    entry_price = Column(Numeric(20, 8), nullable=False)
    current_price = Column(Numeric(20, 8))
    unrealized_pnl = Column(Numeric(20, 8), default=0)
    last_trade_id = Column(String(100))  # 最后更新的交易 ID
    reconcile_status = Column(String(20), default="OK")  # "OK" | "WARNING" | "CRITICAL"
    reconcile_last_check = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 唯一约束：保证 (strategy_id, symbol, side) 唯一
    __table_args__ = (
        UniqueConstraint("strategy_id", "symbol", "side", name="uq_position_snapshot"),
        {"comment": "持仓投影表（运行时真理源）"}
    )
```

#### 3.1.6 log（日志表）

```python
# src/models/log.py
from sqlalchemy import Column, String, DateTime, Text, JSON
from sqlalchemy.sql import func
from src.database.connection import Base

class Log(Base):
    __tablename__ = "log"
    
    log_id = Column(String(100), primary_key=True)
    level = Column(String(20), nullable=False)  # "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"
    component = Column(String(50), nullable=False)  # 模块名称
    message = Column(Text, nullable=False)
    details = Column(JSON)  # 详细信息（JSON）
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    user = Column(String(50))  # 用户（如果是用户操作）
    
    # 索引
    __table_args__ = (
        {"comment": "系统日志表"}
    )
```

### 3.2 Alembic 迁移脚本

```python
# alembic/versions/001_initial_schema.py
"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2026-01-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # dedup_signal 表（信号去重）
    op.create_table(
        'dedup_signal',
        sa.Column('signal_id', sa.String(100), primary_key=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        comment='信号去重表（signal_id 唯一键保证永久去重，不依赖 processed 字段）'
    )
    
    # decision_order_map 表（决策订单映射）
    op.create_table(
        'decision_order_map',
        sa.Column('decision_id', sa.String(100), primary_key=True),
        sa.Column('local_order_id', sa.String(100), nullable=True),  # 本地订单号（可空，支持先占位后下单）
        sa.Column('exchange_order_id', sa.String(100), nullable=True),  # 交易所订单号（可空）
        sa.Column('status', sa.String(20), default='RESERVED'),  # "RESERVED" | "FILLED" | "FAILED" | "TIMEOUT" | "UNKNOWN"
        sa.Column('reserved_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        comment='决策订单映射表（decision_id 唯一键保证幂等，支持两段式幂等：先占位后下单）'
    )
    
    # trade 表（交易记录）
    op.create_table(
        'trade',
        sa.Column('trade_id', sa.String(100), primary_key=True),
        sa.Column('strategy_id', sa.String(50), nullable=False),
        sa.Column('signal_id', sa.String(100), nullable=False),
        sa.Column('decision_id', sa.String(100), nullable=False),
        sa.Column('execution_id', sa.String(100), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('price', sa.Numeric(20, 8), nullable=False),
        sa.Column('slippage', sa.Numeric(20, 8), default=0),
        sa.Column('realized_pnl', sa.Numeric(20, 8), default=0),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_simulated', sa.Boolean(), default=False),  # Phase 1.0 paper 模式均为 False，实盘 Active 交易也为 False
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        comment='交易记录表'
    )
    op.create_index('idx_trade_signal_id', 'trade', ['signal_id'])
    op.create_index('idx_trade_decision_id', 'trade', ['decision_id'])
    op.create_index('idx_trade_strategy_id', 'trade', ['strategy_id'])
    
    # orders 表（订单，避免 SQL 关键字冲突）
    op.create_table(
        'orders',
        sa.Column('order_id', sa.String(100), primary_key=True),
        sa.Column('exchange_order_id', sa.String(100)),
        sa.Column('strategy_id', sa.String(50), nullable=False),
        sa.Column('decision_id', sa.String(100), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('filled_quantity', sa.Numeric(20, 8), default=0),
        sa.Column('price', sa.Numeric(20, 8)),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        comment='订单表'
    )
    op.create_index('idx_orders_decision_id', 'orders', ['decision_id'])
    op.create_index('idx_orders_strategy_id', 'orders', ['strategy_id'])
    op.create_index('idx_orders_status', 'orders', ['status'])
    
    # position_snapshot 表（持仓投影表）
    op.create_table(
        'position_snapshot',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('strategy_id', sa.String(50), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('entry_price', sa.Numeric(20, 8), nullable=False),
        sa.Column('current_price', sa.Numeric(20, 8)),
        sa.Column('unrealized_pnl', sa.Numeric(20, 8), default=0),
        sa.Column('last_trade_id', sa.String(100)),
        sa.Column('reconcile_status', sa.String(20), default='OK'),
        sa.Column('reconcile_last_check', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        comment='持仓投影表（运行时真理源）'
    )
    # 唯一约束：保证 (strategy_id, symbol, side) 唯一
    op.create_unique_constraint(
        'uq_position_snapshot',
        'position_snapshot',
        ['strategy_id', 'symbol', 'side']
    )
    
    # log 表（日志）
    op.create_table(
        'log',
        sa.Column('log_id', sa.String(100), primary_key=True),
        sa.Column('level', sa.String(20), nullable=False),
        sa.Column('component', sa.String(50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('details', sa.JSON()),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('user', sa.String(50)),
        comment='系统日志表'
    )
    op.create_index('idx_log_timestamp', 'log', ['timestamp'])
    op.create_index('idx_log_level', 'log', ['level'])
    op.create_index('idx_log_component', 'log', ['component'])

def downgrade():
    op.drop_table('log')
    op.drop_table('position_snapshot')
    op.drop_table('orders')
    op.drop_table('trade')
    op.drop_table('decision_order_map')
    op.drop_table('dedup_signal')
```

---

## 四、接口 Stub + 最小 Happy Path 串联

### 4.1 FastAPI 应用入口（src/app/main.py）

```python
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging

from src.app.dependencies import get_db_session, get_dependencies_with_session, set_session_factory
from src.utils.logging import setup_logging
from src.utils.config import load_config

logger = logging.getLogger(__name__)

# 应用生命周期
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 加载配置（支持环境变量注入，测试环境可通过 monkeypatch.setenv 注入）
    config = load_config()
    
    # 初始化日志
    setup_logging(
        log_level=config.get("logging", {}).get("level", "INFO"),
        log_file=config.get("logging", {}).get("file"),
        log_to_database=config.get("logging", {}).get("database", False)
    )
    
    # 启动时初始化 SessionFactory（全局单例）
    from src.database.connection import init_session_factory
    session_factory = await init_session_factory(config["database"])
    
    # 将 SessionFactory 设置到 dependencies 模块（单一权威实现）
    set_session_factory(session_factory)
    
    # 保存配置（用于请求中创建依赖）
    app.state.config = config
    logger.info("Application started")
    yield
    # 关闭时清理
    logger.info("Application shutdown")

# 创建 FastAPI 应用（工厂模式，支持测试环境配置注入）
def create_app() -> FastAPI:
    """
    应用工厂函数（支持测试环境配置注入）
    
    使用方式：
    - 生产环境：app = create_app()
    - 测试环境：在 monkeypatch.setenv(...) 后调用 create_app()
    
    约束：所有测试配置注入（TV_WEBHOOK_SECRET、DATABASE_URL 等）必须发生在 app/lifespan 初始化之前
    """
    app = FastAPI(
        title="Trading System API",
        version="0.1.0",
        lifespan=lifespan
    )
    return app

# 生产环境直接创建应用
app = create_app()

# Webhook 路由
@app.post("/webhook/tradingview")
async def receive_webhook(request: Request):
    """接收 TradingView Webhook（每请求创建 session）"""
    config = request.app.state.config
    
    # 每请求创建 session 和依赖
    async with get_db_session() as db_session:
        deps = await get_dependencies_with_session(config, db_session)
        
        try:
            # 1. SignalReceiver 接收并验证
            raw_signal = await deps.signal_receiver.receive(request)
            
            # 2. SignalParser 解析和去重
            standardized_signal = await deps.signal_parser.parse(raw_signal)
            if standardized_signal is None:
                # 重复信号，返回 200 OK（避免 TradingView 重试）
                return JSONResponse(
                    status_code=200,
                    content={"status": "ok", "message": "duplicate signal"}
                )
            
            # 3. 单策略路由（Phase 1.0 固定单策略，直接到 Executor，无 StrategyManager）
            # 4. StrategyExecutor 生成决策
            # 获取策略ID（Phase 1.0 固定单策略，从配置读取）
            strategy_id = config["strategy"]["strategy_id"]
            decision = await deps.strategy_executor.execute(
                standardized_signal,
                positions=await deps.position_manager.get_all_positions(strategy_id),  # 使用新增方法
                market_data=await deps.market_data_adapter.get_market_data(standardized_signal.symbol)
            )
            
            # 5. RiskManager 风控检查
            risk_result = await deps.risk_manager.check(decision)
            if not risk_result.passed:
                logger.warning(f"Risk check failed: {risk_result.rejected_reasons}")
                return JSONResponse(
                    status_code=200,
                    content={"status": "rejected", "reason": risk_result.rejected_reasons}
                )
            
            # 6. ExecutionEngine 执行订单
            execution_result = await deps.execution_engine.execute(decision)
            
            # 7. 返回结果
            return JSONResponse(
                status_code=200,
                content={
                    "status": "ok",
                    "execution_id": execution_result.execution_id,
                    "order_id": execution_result.order_id
                }
            )
        
        except Exception as e:
            logger.error(f"Error processing webhook: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.app.main:app",
        host="0.0.0.0",
        port=8000,
        workers=1  # 单实例约束
    )
```

### 4.2 依赖注入（src/app/dependencies.py）

```python
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from contextlib import asynccontextmanager
from src.signal.receiver import SignalReceiver
from src.signal.parser import SignalParser
from src.strategy.executor import StrategyExecutor  # Phase 1.0 单策略，无 StrategyManager
from src.risk.manager import RiskManager
from src.execution.engine import ExecutionEngine
from src.execution.order_manager import OrderManager
from src.position.manager import PositionManager
from src.account.manager import AccountManager
from src.adapters.tradingview import TradingViewAdapter
from src.adapters.exchange import ExchangeAdapter
from src.adapters.market_data import MarketDataAdapter
from src.repositories.trade import TradeRepository
from src.repositories.order import OrderRepository
from src.repositories.position_snapshot import PositionSnapshotRepository
from src.repositories.dedup_signal import DedupSignalRepository
from src.repositories.decision_order_map import DecisionOrderMapRepository

# SessionFactory（全局单例，在应用启动时通过 set_session_factory 设置）
AsyncSessionFactory: Optional[async_sessionmaker[AsyncSession]] = None

def set_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    """设置 SessionFactory（由 lifespan 调用，单一权威实现）"""
    global AsyncSessionFactory
    AsyncSessionFactory = factory

@asynccontextmanager
async def get_db_session() -> AsyncSession:
    """
    每请求/每任务创建 session（异步上下文管理器，单一权威实现）
    
    使用方式：
        async with get_db_session() as session:
            # 使用 session
            ...
        # async with 自动负责 session 的关闭与回收，无需手动调用 close()
    
    注意：这是 @asynccontextmanager 装饰的异步上下文管理器，不是 FastAPI Depends 的 yield dependency
    """
    if AsyncSessionFactory is None:
        raise RuntimeError("SessionFactory not initialized. Call set_session_factory() in lifespan.")
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        # 注意：async with AsyncSessionFactory() 已负责 session 的关闭与回收，无需额外调用 session.close()

class Dependencies:
    """依赖容器（所有字段显式声明）"""
    def __init__(self):
        # 信号处理
        self.signal_receiver: SignalReceiver = None
        self.signal_parser: SignalParser = None
        
        # 策略执行
        self.strategy_executor: StrategyExecutor = None  # Phase 1.0 单策略，无 StrategyManager
        
        # 风控
        self.risk_manager: RiskManager = None
        
        # 执行
        self.execution_engine: ExecutionEngine = None
        self.order_manager: OrderManager = None
        
        # 账户和持仓
        self.position_manager: PositionManager = None
        self.account_manager: AccountManager = None
        
        # 适配器
        self.market_data_adapter: MarketDataAdapter = None
        self.exchange_adapter: ExchangeAdapter = None
        
        # Repository（显式声明，避免动态属性遗漏）
        self.dedup_signal_repo: DedupSignalRepository = None
        self.decision_order_map_repo: DecisionOrderMapRepository = None
        self.trade_repo: TradeRepository = None
        self.order_repo: OrderRepository = None
        self.position_snapshot_repo: PositionSnapshotRepository = None

# 注意：get_dependencies(config) 已弃用，存在"半初始化风险"（无法创建依赖 session 的组件）
# 请使用 get_dependencies_with_session(config, db_session) 替代
# 
# async def get_dependencies(config: Dict[str, Any]) -> Dependencies:
#     """[已弃用] 此函数无法完整初始化依赖，因为 Repository 等组件需要 session"""
#     ...

# 改进：在请求处理函数中创建 session 和 repo
async def get_dependencies_with_session(config: Dict[str, Any], db_session: AsyncSession) -> Dependencies:
    """初始化依赖（使用传入的 session）"""
    deps = Dependencies()
    
    # 适配器（无状态，可共享）
    deps.market_data_adapter = MarketDataAdapter(config["exchange"])
    deps.exchange_adapter = ExchangeAdapter(config["exchange"], config["product_type"])
    
    # Repository（使用传入的 session）
    deps.dedup_signal_repo = DedupSignalRepository(db_session)
    deps.decision_order_map_repo = DecisionOrderMapRepository(db_session)
    deps.trade_repo = TradeRepository(db_session)
    deps.order_repo = OrderRepository(db_session)
    deps.position_snapshot_repo = PositionSnapshotRepository(db_session)
    
    # 信号处理
    deps.signal_receiver = SignalReceiver(
        TradingViewAdapter(),
        config["tradingview"]["webhook_secret"]
    )
    deps.signal_parser = SignalParser(deps.dedup_signal_repo)
    
    # 策略
    deps.strategy_executor = StrategyExecutor(config["strategy"])
    
    # 账户和持仓
    deps.account_manager = AccountManager(deps.exchange_adapter)
    deps.position_manager = PositionManager(
        deps.position_snapshot_repo,
        deps.trade_repo
    )
    
    # 风控
    deps.risk_manager = RiskManager(
        deps.position_manager,
        deps.account_manager,
        config["risk"]
    )
    
    # 执行
    deps.execution_engine = ExecutionEngine(
        exchange_adapter=deps.exchange_adapter,
        decision_order_repo=deps.decision_order_map_repo,
        trade_repo=deps.trade_repo,
        order_repo=deps.order_repo,
        position_manager=deps.position_manager
    )
    deps.order_manager = OrderManager(
        deps.exchange_adapter,
        deps.order_repo
    )
    
    return deps
```

### 4.3 最小 Happy Path 测试

```python
# tests/integration/test_happy_path.py
import pytest
from fastapi.testclient import TestClient
from src.app.main import create_app  # 使用工厂模式，禁止直接 import app

# 集成测试数据库策略（唯一口径）：推荐 SQLite
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

@pytest.fixture(scope="function")
def app(monkeypatch):
    """
    集成测试 App 启动时机（唯一口径）：
    1. 先 monkeypatch.setenv(...)（包括 TV_WEBHOOK_SECRET、DATABASE_URL）
    2. 再调用 create_app()
    3. 再创建 TestClient(app)
    
    约束：所有测试配置注入必须发生在 app/lifespan 初始化之前
    """
    # 1. 配置注入（必须在 app/lifespan 初始化之前）
    test_webhook_secret = "test_webhook_secret"  # 测试环境固定 secret
    monkeypatch.setenv("TV_WEBHOOK_SECRET", test_webhook_secret)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    
    # 2. 创建应用（工厂模式）
    app = create_app()
    
    # 3. 测试启动前自动建表或迁移（SQLite 方案）
    # 集成测试数据库策略（唯一口径）：推荐 SQLite，测试启动前自动建表或迁移
    # 方案A（推荐）：使用 Alembic 在 fixture 中运行迁移
    # from alembic.config import Config
    # from alembic import command
    # alembic_cfg = Config("alembic.ini")
    # command.upgrade(alembic_cfg, "head")
    # 
    # 方案B：直接使用 SQLAlchemy 创建表（仅测试环境）
    # from src.database.connection import Base, engine
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)
    #
    # 注意：如果使用 Docker Postgres，需要在 fixture 中启动容器、等待 ready、跑迁移
    # 约束：测试不依赖本地已有数据库、不依赖人工先跑命令，新机器可直接跑
    
    return app

@pytest.fixture(scope="function")
def client(app):
    """创建 TestClient"""
    return TestClient(app)

def test_happy_path(client):
    """测试完整 Happy Path"""
    # 1. 发送 TradingView Webhook
    webhook_data = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-01-26T10:00:00Z",
        "indicator_name": "MOCK_INDICATOR",
        "confidence": 0.8,
        "price": 50000.0
    }
    
    # 集成测试验签 secret 的闭环来源（唯一口径）：
    # 测试中用于计算 HMAC 的 webhook_secret 必须与应用运行时加载的 TV_WEBHOOK_SECRET 完全一致
    # 禁止"测试里算一个 secret，应用里读另一个 secret"的隐式配置
    import hmac
    import hashlib
    import base64
    import json
    import os
    
    # 从环境变量读取（与 app 运行时加载的完全一致）
    webhook_secret = os.getenv("TV_WEBHOOK_SECRET", "test_webhook_secret")
    
    # 固定 separators 和 sort_keys，确保 payload bytes 稳定
    payload_bytes = json.dumps(webhook_data, separators=(',', ':'), sort_keys=True).encode('utf-8')
    signature = base64.b64encode(
        hmac.new(webhook_secret.encode('utf-8'), payload_bytes, hashlib.sha256).digest()
    ).decode('utf-8')
    
    # 使用 data=payload_bytes 发送，确保验签基于同一份 body bytes
    response = client.post(
        "/webhook/tradingview",
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-TradingView-Signature": signature  # 真实 HMAC 签名
        }
    )
    
    # 2. 验证响应
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "execution_id" in data
    assert "order_id" in data
    
    # 3. 验证数据库记录
    # - dedup_signal 表有记录
    # - decision_order_map 表有记录
    # - trade 表有记录
    # - orders 表有记录
    # - position_snapshot 表有更新

def test_duplicate_signal(client):
    """测试信号去重（使用真实 HMAC 签名）"""
    webhook_data = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "timestamp": "2026-01-26T10:00:00Z",
        "indicator_name": "MOCK_INDICATOR",
        "confidence": 0.8
    }
    
    # 集成测试验签 secret 的闭环来源（唯一口径）：
    # 测试中用于计算 HMAC 的 webhook_secret 必须与应用运行时加载的 TV_WEBHOOK_SECRET 完全一致
    import hmac
    import hashlib
    import base64
    import json
    import os
    
    # 从环境变量读取（与 app 运行时加载的完全一致）
    webhook_secret = os.getenv("TV_WEBHOOK_SECRET", "test_webhook_secret")
    
    # 固定 separators 和 sort_keys，确保 payload bytes 稳定
    payload_bytes = json.dumps(webhook_data, separators=(',', ':'), sort_keys=True).encode('utf-8')
    signature = base64.b64encode(
        hmac.new(webhook_secret.encode('utf-8'), payload_bytes, hashlib.sha256).digest()
    ).decode('utf-8')
    
    # 第一次发送：使用 data=payload_bytes 发送，确保验签基于同一份 body bytes
    response1 = client.post(
        "/webhook/tradingview",
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-TradingView-Signature": signature
        }
    )
    assert response1.status_code == 200
    
    # 第二次发送（相同 signal_id，相同签名）：使用相同的 payload_bytes
    response2 = client.post(
        "/webhook/tradingview",
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-TradingView-Signature": signature
        }
    )
    assert response2.status_code == 200
    assert response2.json()["message"] == "duplicate signal"
    
    # 验证只生成 1 个交易决策
    # ...
```

---

## 五、关键约束遵守检查清单

### ✅ 单实例运行
- [ ] `uvicorn workers=1` 配置正确
- [ ] Docker Compose 中 workers=1
- [ ] 禁止多进程/多实例部署

### ✅ DB 幂等
- [ ] `dedup_signal.signal_id` 为 PRIMARY KEY（唯一约束）
- [ ] `decision_order_map.decision_id` 为 PRIMARY KEY（唯一约束）
- [ ] `decision_order_map.local_order_id` 为可空字段（支持先占位后下单）
- [ ] `decision_order_map.exchange_order_id` 为可空字段（交易所订单号）
- [ ] `decision_order_map` 包含 `status` 和 `reserved_at` 字段（支持占位状态）
- [ ] 字段语义明确：`local_order_id`=本地订单号，`exchange_order_id`=交易所订单号
- [ ] 使用 `INSERT ... ON CONFLICT` 或 `INSERT IGNORE`

### ✅ 无队列
- [ ] 不使用 Celery/Redis/消息队列
- [ ] 定时任务使用 APScheduler 或 asyncio task（进程内调度）

### ✅ Compose 单机单实例
- [ ] Docker Compose 配置：1 app + 1 DB
- [ ] 禁止扩容与多实例
- [ ] workers=1 明确配置

### ✅ 交易所与产品形态固定
- [ ] 配置字段：`exchange.name`、`exchange.sandbox`、`product_type`
- [ ] Phase 1.0 禁止扩展

---

**文档结束**
