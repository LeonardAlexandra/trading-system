# Superpowers 使用说明（Cursor 版）

本文档介绍如何在 Cursor 中使用 Superpowers 技能包，包含安装验证、技能清单、工作流说明及详细案例。

---

## 一、安装验证

### 1.1 安装位置

| 组件 | 路径 |
|------|------|
| Superpowers 源码 | `~/.cursor/superpowers/` |
| 全局 Skills 目录 | `~/.cursor/skills/` |
| Superpowers 符号链接 | `~/.cursor/skills/superpowers-*` |

### 1.2 自检命令

在终端执行以下命令验证安装：

```bash
# 检查 Superpowers 是否已克隆
ls -la ~/.cursor/superpowers/skills/

# 检查 14 个 skill 符号链接是否生效
ls -la ~/.cursor/skills/ | grep superpowers

# 验证任一 skill 可读
head -10 ~/.cursor/skills/superpowers-test-driven-development/SKILL.md
```

**预期输出**：应看到 14 个 `superpowers-*` 符号链接，且能正常读取 SKILL.md 内容。

### 1.4 自检结果（安装完成后）

```
=== 1. Superpowers 源码 === ✓ 14 个 skill 目录
=== 2. Skills 符号链接 === ✓ 14 个 superpowers-* 链接
=== 3. 读取测试 === ✓ SKILL.md 可正常读取
```

> **提示**：若 Cursor 未自动发现新 skills，请启动新对话或重启 Cursor。

### 1.3 触发验证

在 Cursor 对话中尝试以下任一表述，Agent 应能自动加载对应 Superpowers skill：

- 「帮我想一个功能设计方案」→ 触发 **superpowers-brainstorming**
- 「实现这个 bug 修复前先写测试」→ 触发 **superpowers-test-driven-development**
- 「我有一个多步骤的需求，帮我写实现计划」→ 触发 **superpowers-writing-plans**
- 「遇到这个 bug，帮我系统化排查」→ 触发 **superpowers-systematic-debugging**

---

## 二、技能清单

| 技能名称 | 触发场景 | 核心作用 |
|----------|----------|----------|
| **superpowers-brainstorming** | 创建功能、修改行为、设计组件前 | 通过问答澄清需求，分小节呈现设计，保存到 `docs/plans/` |
| **superpowers-writing-plans** | 已有需求/规格，尚未写代码时 | 将多步骤任务拆成 2–5 分钟可完成的小任务，含文件路径、代码片段、验证步骤 |
| **superpowers-executing-plans** | 有书面实现计划待执行时 | 按任务分批执行，带人工检查点 |
| **superpowers-subagent-driven-development** | 执行含独立子任务的实现计划时 | 每任务分配子 Agent，两阶段评审（规格符合性 → 代码质量） |
| **superpowers-test-driven-development** | 实现新功能或修 bug 前 | 强制 RED-GREEN-REFACTOR：先写失败测试 → 跑通 → 写最少实现 → 重构 |
| **superpowers-systematic-debugging** | 遇到 bug、测试失败或异常行为时 | 四阶段根因分析：复现 → 隔离 → 假设 → 验证 |
| **superpowers-verification-before-completion** | 声称工作完成/修复/通过前 | 要求先运行验证命令并确认输出，再声明完成 |
| **superpowers-requesting-code-review** | 完成任务、实现重要功能或合并前 | 对照计划做预评审，按严重程度报告问题 |
| **superpowers-receiving-code-review** | 收到代码评审反馈时 | 强调技术严谨与验证，而非形式化同意 |
| **superpowers-using-git-worktrees** | 需与当前工作区隔离、或执行实现计划前 | 创建独立 git worktree，运行项目初始化并验证测试基线 |
| **superpowers-finishing-a-development-branch** | 实现完成、测试通过，需决定如何集成时 | 引导选择：合并、PR、保留或丢弃分支 |
| **superpowers-dispatching-parallel-agents** | 有 2+ 独立、无共享状态的任务时 | 并发调度多个子 Agent 并行处理 |
| **superpowers-writing-skills** | 创建、编辑或验证 Skill 时 | 将 TDD 用于 Skill：压力场景 → 失败基线 → 编写 Skill → 验证 |
| **superpowers-using-superpowers** | 对话开始时 | 建立技能使用规则：有 1% 可能适用就必须检查并调用 skill |

---

## 三、与 skill-creator / writing-skills 的兼容关系

| 技能 | 来源 | 典型用途 |
|------|------|----------|
| **skill-creator** | Cursor 内置 | 首次创建 Skill、需要 `init_skill.py` / `package_skill.py` 等脚本支持 |
| **superpowers-writing-skills** | Superpowers | 对 Skill 做 TDD 式验证、压力测试、堵住漏洞 |

**建议**：新建 Skill 时用 skill-creator 搭建骨架；需要验证质量时用 superpowers-writing-skills 做 TDD 迭代。两者可同时存在，无冲突。

---

## 四、推荐工作流

```
创意/需求
    ↓
superpowers-brainstorming（澄清需求、产出设计文档）
    ↓
superpowers-using-git-worktrees（可选：创建隔离工作区）
    ↓
superpowers-writing-plans（产出实现计划）
    ↓
superpowers-subagent-driven-development 或 superpowers-executing-plans（执行计划）
    ↓
superpowers-test-driven-development（贯穿实现过程）
    ↓
superpowers-requesting-code-review（任务间/合并前）
    ↓
superpowers-finishing-a-development-branch（收尾分支）
```

---

## 五、详细案例

### 案例 1：从零设计并实现一个新功能

**场景**：需要为交易系统增加「风控阈值配置」功能。

**步骤 1：触发 brainstorming**

在 Cursor 中输入：

> 我想加一个风控阈值配置功能，让用户可以设置最大持仓、单笔限额等。帮我先做需求澄清和设计。

**预期**：Agent 加载 superpowers-brainstorming，逐轮提问（如：配置存储在哪儿？生效时机？是否有权限？），然后分小节给出设计（200–300 字/节），并保存到 `docs/plans/YYYY-MM-DD-risk-threshold-config-design.md`。

**步骤 2：触发 writing-plans**

设计确认后，继续输入：

> 设计已经确认，请基于设计文档写一份实现计划。

**预期**：Agent 加载 superpowers-writing-plans，产出计划文档，包含：

- 每个任务的精确文件路径
- 测试先行步骤（如先写 `test_risk_threshold_config.py`）
- 最小实现步骤
- 验证命令（如 `pytest tests/test_risk_threshold_config.py -v`）

**步骤 3：执行计划**

输入：

> 按照实现计划，逐任务执行，每个任务完成后做一次自查。

**预期**：Agent 按 superpowers-executing-plans 或 superpowers-subagent-driven-development 执行，每步包含运行测试、提交等。

---

### 案例 2：修 Bug 时强制 TDD

**场景**：某个接口在并发下偶发返回 500。

**步骤 1：触发 test-driven-development**

输入：

> 有个接口在并发下偶尔 500，修这个 bug 前先按 TDD 来：先写能复现的失败测试，再修。

**预期**：Agent 加载 superpowers-test-driven-development，执行：

1. 写一个失败测试（例如 `test_concurrent_request_returns_200`）
2. 运行测试确认失败
3. 写最少实现让测试通过
4. 运行测试确认通过
5. 视情况重构

---

### 案例 3：系统化排查未知 Bug

**场景**：测试套件中某个用例间歇性失败，原因不明。

**步骤 1：触发 systematic-debugging**

输入：

> 有个测试间歇性失败，帮我用系统化调试方法找出根因。

**预期**：Agent 加载 superpowers-systematic-debugging，执行四阶段：

1. **复现**：描述如何稳定复现
2. **隔离**：通过二分或排除法缩小范围
3. **假设**：提出可能根因
4. **验证**：用最小实验验证假设

并可能引用 `root-cause-tracing.md`、`condition-based-waiting.md` 等子文档。

---

### 案例 4：在声明「修好了」前强制验证

**场景**：Agent 已修改代码，准备说「bug 已修复」。

**步骤 1：触发 verification-before-completion**

输入：

> 在你说修好之前，请先跑一遍相关测试和校验命令，把实际输出贴出来，再下结论。

**预期**：Agent 加载 superpowers-verification-before-completion，先执行 `pytest ...` 等命令，展示真实输出，再基于证据给出结论，而不是只做口头声明。

---

### 案例 5：创建新 Skill 并做 TDD 验证

**场景**：想为项目增加一个「回测报告生成」Skill。

**步骤 1：用 skill-creator 搭骨架**

输入：

> 帮我用 skill-creator 创建一个 backtest-report skill，用于生成标准化回测报告。

**预期**：Agent 按 skill-creator 流程，运行 `init_skill.py`，生成目录结构、SKILL.md 模板和 `references/`、`scripts/` 等。

**步骤 2：用 superpowers-writing-skills 做 TDD 验证**

输入：

> 用 writing-skills 的 TDD 方法验证这个 backtest-report skill：先设计压力场景，看没有 skill 时的基线行为，再完善 skill，确保能通过验证。

**预期**：Agent 加载 superpowers-writing-skills，执行：

1. 设计压力场景（如「用户要求生成报告但缺少必要字段」）
2. 在无 skill 情况下跑场景，记录失败行为
3. 完善 SKILL.md，针对性解决这些失败
4. 再次跑场景，确认 skill 生效

---

### 案例 6：与 Phase1.1 模块任务结合

**场景**：在执行 Phase1.1 交付包中 D3 开发项时，希望同时遵循 TDD 和调试规范。

**兼容方式**：Phase1.1 模块任务 skill 定义的是「条款对齐 → 实现 → 证据包」的固定流程；Superpowers 的 TDD 与调试技能用于实现过程中的方法论。

**示例输入**：

> # Module Task: D3 - 风控失败 → 挂起全链路测试
>
> 按 Phase1.1 模块任务流程执行。实现和测试时遵循 TDD：先写失败测试，再写最少实现。

**预期**：Agent 同时参考 phase11-module-task 与 superpowers-test-driven-development，既满足交付包条款，又按 RED-GREEN-REFACTOR 完成实现。

---

## 六、更新与维护

### 更新 Superpowers

```bash
cd ~/.cursor/superpowers && git pull
```

符号链接会直接指向最新内容，无需重新创建。

### 卸载

删除符号链接（保留源码可选）：

```bash
cd ~/.cursor/skills
rm superpowers-brainstorming superpowers-dispatching-parallel-agents \
   superpowers-executing-plans superpowers-finishing-a-development-branch \
   superpowers-receiving-code-review superpowers-requesting-code-review \
   superpowers-subagent-driven-development superpowers-systematic-debugging \
   superpowers-test-driven-development superpowers-using-git-worktrees \
   superpowers-using-superpowers superpowers-verification-before-completion \
   superpowers-writing-plans superpowers-writing-skills
```

---

## 七、参考链接

- [Superpowers 官方仓库](https://github.com/obra/superpowers)
- [Superpowers 博客介绍](https://blog.fsck.com/2025/10/09/superpowers/)
- [Cursor 兼容说明](~/.cursor/superpowers/CURSOR_README.md)
