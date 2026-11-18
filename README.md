# ScoutMind

FM27 智能球探、球员成长与转会决策平台。Windows 桌面端 + 本地后端，数据全部留在本机。

ScoutMind 读取 Football Manager 27 的可验证数据（游戏运行时快照或存档解析），建立跨时间的球员与交易数据库，
再用确定性统计和可解释的角色评分回答「这个球员值多少」「年轻球员该不该卖」「哪些俱乐部低买高卖」这类问题。
LLM 只负责理解问题与组织解释，所有数字来自数据库和算法。

> **当前状态：源码完整、演示数据可跑，真实 FM27 读取尚未验证。**
> 后端（31 个用例）、前端（类型检查 + 生产构建）、C# 读取器（46 个自检用例）、Desktop Agent（同步链路）均已通过验证；
> 仓库自带一份明确标注的合成演示数据（`source=synthetic_fixture`），用于在没有真实扫描结果时验证界面和算法。
>
> 本机实测：Steam Build `26620374`、`game_plugin.dll` `27.1.0+2505117`（路径 `fm_Data\Plugins\x86_64`），
> 不在已知候选组合内，读取器返回 `Unknown`/`candidate` 并拒绝扫描。要真正读取，需要配置一个经过审查的外部扫描器、
> 确认其支持该构建、把兼容条目改为 `verified` 后跑通 `probe`。在此之前任何界面上的数字都只代表演示数据。

## 目录结构

```
scoutmind/
├── backend/          FastAPI + SQLAlchemy + Alembic（球员、快照、转会、分析、AI 工具）
├── frontend/         Vue 3 + TypeScript + Element Plus + ECharts（8 个业务页面）
├── live-reader/      C#/.NET 只读读取器 CLI（Steam 检测、版本校验、probe、scan）
├── desktop-agent/    C#/.NET 桌面代理（调度扫描、导出、同步到本地 API）
├── database/         PostgreSQL 初始化说明与迁移入口
├── docs/             产品、架构、协议、读取器、转会分析、安全文档
├── samples/demo/     合成演示扫描报文（JSON，可直接导入）
├── scripts/          安装、启动、导入、演示数据、Windows 发布脚本
├── docker-compose.yml
└── README.md
```

## 快速开始（Windows）

```powershell
# 1. 后端：创建虚拟环境并安装依赖
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 初始化数据库（SQLite 默认，零配置）
.\.venv\Scripts\python.exe -m alembic upgrade head

# 3. 生成并导入演示数据（可重复执行，--force 重建）
cd ..
.\backend\.venv\Scripts\python.exe scripts\seed_demo.py --force

# 4. 启动后端（仅 127.0.0.1）
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# 5. 前端（另开终端）
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173
```

打开 `http://127.0.0.1:5173` 即可看到概览、球员中心、成长追踪、智能球探、Transfer Intelligence、AI 决策中心和数据诊断页面。

> 本仓库当前这份拷贝已经装好 `backend/.venv`、`frontend/node_modules` 与演示数据库，可直接运行
> `.\scripts\run-backend.ps1` 与 `.\scripts\run-frontend.ps1`；删掉这些目录后按上面步骤重装即可。

![概览](docs/assets/dashboard.png)

| 球员中心 | 转会情报 |
| --- | --- |
| ![球员中心](docs/assets/players.png) | ![转会情报](docs/assets/transfers.png) |

截图来自内置合成演示数据（界面顶部始终显示演示数据横幅），不代表任何真实 FM27 存档。

需要 PostgreSQL 时：`docker compose up -d postgres`，然后设置
`SCOUTMIND_DATABASE_URL=postgresql+psycopg://scoutmind:scoutmind@127.0.0.1:5432/scoutmind` 并执行 `alembic upgrade head`。

## 真实数据接入流程

真实 FM27 数据必须经过「读取器 → 扫描报文 → 导入」三步，任何一步失败都不会写入数据：

```powershell
# 1. 编译并发布 C# 读取器（需要 .NET SDK 10）
.\scripts\publish-windows.ps1

# 2. 检测：未启动游戏时返回 NotFound，不崩溃
.\publish\win-x64\ScoutMind.LiveReader.exe status

# 3. 版本兼容通过后 probe（probe 失败必须停止，不得绕过版本校验）
.\publish\win-x64\ScoutMind.LiveReader.exe probe

# 4. 执行一次只读扫描，输出原始 JSON
.\publish\win-x64\ScoutMind.LiveReader.exe scan --output .\exports

# 5. 导入到本地后端（幂等，使用 scan_id 去重）
.\scripts\import-scan.ps1 -Path .\exports\scan-<id>.json
```

读取器只读取游戏进程内存，绝不写入；版本不匹配时拒绝扫描。兼容清单里的
`Steam App ID 4530370 / Build 26577676 / game_plugin.dll 27.0.1+2503222` 是**候选值**，必须在本机 probe
验证后才允许扫描，详见 `docs/VERSION_COMPATIBILITY.md`。

## 设计原则

- **事实与推断分离**：`source` 字段区分 `fm27_live_reader` / `fm_save_parser` / `manual` / `ocr` / `external` /
  `estimated` / `synthetic_fixture`；界面和 AI 回答都要显示来源。
- **未知值保持 NULL**：CA、PA、隐藏属性、成交费用缺失时写 `NULL`，不用 0 冒充。
- **快照只追加**：`player_snapshots` 以 `(instance, observed_at)` 去重，历史不可被后续导入覆盖。
- **统计优先**：中位数与 25/75 分位优先于平均数；样本不足时拒绝给出精确估值。
- **可追溯**：每次统计、估值、评分都带 `algorithm_version`、样本量、字段覆盖率。
- **本地优先**：API 只监听 `127.0.0.1`，可选 `X-ScoutMind-Token` 鉴权，CORS 仅允许本地来源。

## 测试

```powershell
# 后端（31 个用例：导入幂等、快照追加、身份复用、费用口径、统计/相似/估值、AI 不编造、鉴权）
cd backend
python -m pytest

# 前端类型检查与构建
cd frontend
npm run build

# C# 读取器自检（无外部依赖，离线运行）
dotnet run --project live-reader/tests/ScoutMind.Reader.Tests -c Release
```

## 文档

| 文档 | 内容 |
| --- | --- |
| `docs/PRODUCT_SPEC.md` | 产品定位、模块、场景与验收基线 |
| `docs/ARCHITECTURE.md` | 分层架构、数据流、身份匹配、失败语义 |
| `docs/DATA_PROTOCOL.md` | 扫描报文协议（版本、字段、校验规则） |
| `docs/API.md` | HTTP API 契约（前端与 Agent 的唯一依据） |
| `docs/LIVE_READER.md` | C# 读取器、状态机、CLI、发布 |
| `docs/VERSION_COMPATIBILITY.md` | 版本兼容清单与拒绝策略 |
| `docs/TRANSFER_INTELLIGENCE.md` | 费用口径、统计、相似度、估值 |
| `docs/SECURITY.md` | 本地鉴权、只读约束、数据与许可证边界 |
| `docs/ROADMAP.md` | 阶段划分、当前完成度、下一步 |

## 免责声明

ScoutMind 是玩家自用的数据分析工具，与 Sports Interactive / SEGA 无隶属或授权关系，不包含游戏本体、游戏素材或
他人存档。仅使用你自己机器上的存档与运行数据。代码采用 MIT 许可证；游戏数据、商标和素材的权利不随代码许可证
转移，商业化前必须单独审查。
