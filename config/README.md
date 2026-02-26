# 配置说明

## 数据库连接（DATABASE_URL）

项目使用 **async SQLAlchemy**（`create_async_engine`），数据库 URL 必须与异步驱动匹配。

### SQLite（默认）

开发/测试推荐使用 SQLite，无需额外安装驱动：

```bash
DATABASE_URL=sqlite+aiosqlite:///./trading_system.db
```

### PostgreSQL

**必须使用 asyncpg 驱动**，`DATABASE_URL` 示例：

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
```

示例（本地）：

```bash
DATABASE_URL=postgresql+asyncpg://trading_user:trading_password@localhost:5432/trading_system
```

**注意**：
- 禁止使用 `postgresql://` 或 `postgresql+psycopg2://`（同步驱动），否则会报驱动错误。
- 若配置为上述同步 URL，应用会在启动时抛出 `ValueError`，提示改用 `postgresql+asyncpg://`。

### 配置文件

- `config.example.yaml`：复制为 `config/config.yaml` 后编辑。
- 其中 `database.url` 支持环境变量占位：`"${DATABASE_URL}"`。
