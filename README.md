# ScoutMind

FM27 智能球探、球员成长与转会决策平台。Windows 桌面端 + 本地后端，数据全部留在本机。

ScoutMind 读取 Football Manager 27 的可验证数据（游戏运行时快照或存档解析），建立跨时间的球员与交易数据库，
再用确定性统计和可解释的角色评分回答「这个球员值多少」「年轻球员该不该卖」「哪些俱乐部低买高卖」这类问题。
LLM 只负责理解问题与组织解释，所有数字来自数据库和算法。

> **当前状态：V2 分析层完整；真实 FM27 导出已跑通审查 → 导入 → 端到端；自研读取器已在 FM27 27.1（build 26620374 / 插件 27.1.0+2505117）验证为 Verified，可扫描；其他版本仍拒绝。**
> 后端（377 个用例，含真实导出回归、权限隔离与性能回归）、前端（类型检查 + 生产构建）、C# 读取器（46 个自检用例）、Desktop Agent（同步链路）均已通过验证；
> 仓库自带一份明确标注的合成演示数据（`source=synthetic_fixture`），用于在没有真实扫描结果时验证界面和算法。
>
> 数据接入：除自研 C# 读取器外，已接入 [FMSuperScout](https://github.com/mavarobli/FMSuperScout) 的导出
> （独立适配层 + 字段映射报告 + 幂等导入，见 [docs/FMSUPERSCOUT.md](docs/FMSUPERSCOUT.md)）。
> 已用真实导出（FMSuperScout 1.7.3，48,089 名球员）完成审查与导入验收，记录见
> [docs/acceptance/REAL-RUN-2026-11-18.md](docs/acceptance/REAL-RUN-2026-11-18.md)。
>
> 读取器现在自带原生只读引擎（`live-reader/ScoutMind.FMReader`，内嵌 FMSuperScout 内核，MIT）：
> 不再需要单独安装/启动 FMSuperScout，`ScoutMind.LiveReader.exe scan` 默认走内置引擎。
> 版本闸门按构建号 + 插件版本放行；本机 27.1（build 26620374 / 插件 27.1.0+2505117）已验证为
> `Verified`，可直接扫描，见 [docs/FM27-VERSION-VERIFICATION.md](docs/FM27-VERSION-VERIFICATION.md) 与
> [docs/acceptance/VERIFY-2026-11-20-SM012-READER.md](docs/acceptance/VERIFY-2026-11-20-SM012-READER.md)
> （同一存档连续 10 次真实扫描）。候选构建仍会被拒绝，这是版本闸门的预期行为。
>
> 这份导出没有 `clubs` 数组、没有俱乐部 ID，也没有主执教俱乐部：ScoutMind 用独立的俱乐部解析层
> （稳定 uid + 来源 + 可信度）、手动指定本队与阵容 CSV 导入来解决，见
> [docs/CLUB_RESOLUTION.md](docs/CLUB_RESOLUTION.md)。
>
> V2 已落地的分析能力：阵容智能（六维评分 + 位置深度 + 短板 + 接班）、智能球探引擎（位置模板 + 六维球员评分 +
> 隐藏价值 + 候选名单）、转会情报（成交分位 + 成本模型 + 投资效率 + 交易类型体系 + 复盘）、球员发展（成长速率 +
> 建议 + 潜力区间）、比赛表现分析（分位置产出 + 同位置百分位 + 趋势）与 AI 体育总监（14 个业务工具 + 四类可靠性 + 引用）、身份复核中心、转会模拟器、成长预测与自动引援推荐。
> 每个分数都标注了数据依据与缺失项，口径见 [docs/MODELS.md](docs/MODELS.md)；
> V3 任务状态见 [docs/SCOUTMIND-V3-IMPLEMENTATION-REPORT.md](docs/SCOUTMIND-V3-IMPLEMENTATION-REPORT.md)。
>
> 本机实测：Steam Build `26620374`、`game_plugin.dll` `27.1.0+2505117`（路径 `fm_Data\Plugins\x86_64`），
> 兼容条目为 `Verified`，`probe` 通过、`scan` 可读取真实存档。未验证的构建仍会返回
> `Unknown`/`candidate` 并拒绝扫描；界面上的数字只有在该存档完成真实扫描后才有意义。

## 目录结构

```
scoutmind/
├── backend/          FastAPI + SQLAlchemy + Alembic（球员、快照、统计、转会、阵容/球探/发展/表现、AI 工具）
├── frontend/         Vue 3 + TypeScript + Element Plus + ECharts（8 个主分析页 + 3 个辅助页，深色专业风格）
├── live-reader/      C#/.NET 只读读取器 CLI（Steam 检测、版本校验、probe、scan）
├── desktop-agent/    C#/.NET 桌面代理（调度扫描、导出、同步到本地 API）
├── database/         PostgreSQL 初始化说明与迁移入口
├── docs/             产品、架构、协议、FMSuperScout 接入、模型口径、安全文档
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

打开 `http://127.0.0.1:5173` 即可看到概览、阵容智能、智能球探引擎、转会情报、球员发展、表现分析、AI 体育总监与数据中心，
以及球员中心、角色球探、关注名单三个辅助页面。

> 本仓库当前这份拷贝已经装好 `backend/.venv`、`frontend/node_modules` 与演示数据库，可直接运行
> `.\scripts\run-backend.ps1` 与 `.\scripts\run-frontend.ps1`；删掉这些目录后按上面步骤重装即可。

![概览](docs/assets/dashboard.png)

| 阵容智能 | 智能球探引擎 |
| --- | --- |
| ![阵容智能](docs/assets/squad.png) | ![智能球探引擎](docs/assets/recruitment.png) |

| 球员中心 | 转会情报 |
| --- | --- |
| ![球员中心](docs/assets/players.png) | ![转会情报](docs/assets/transfers.png) |

截图来自内置合成演示数据（界面顶部始终显示演示数据横幅），不代表任何真实 FM27 存档。

需要 PostgreSQL 时：`docker compose up -d postgres`，然后设置
`SCOUTMIND_DATABASE_URL=postgresql+psycopg://scoutmind:scoutmind@127.0.0.1:5432/scoutmind` 并执行 `alembic upgrade head`。

## 数据接入：FMSuperScout（推荐先走这条）

[FMSuperScout](https://github.com/mavarobli/FMSuperScout) 是开源的 FM27/FM26 读取器（MIT）。它把整库读成一份 JSON 导出，
ScoutMind 用**独立适配层**读取这份导出：核心业务代码不认识对方格式，转换仍产出标准扫描报文，走同一条幂等导入路径。

```powershell
# 1. 在游戏里按 F9 导出，先跑真实数据审查（P0-1，不写库）
.\scripts\import-fmscout.ps1 -Validate

# 2. 需要字段级细节时再看映射报告（同样不写库）
.\scripts\import-fmscout.ps1 -Preview

# 3. 确认无误后导入（同一份导出重复导入返回 duplicate=true）
.\scripts\import-fmscout.ps1

# 4. 定时同步 / 实时监听（FMSuperScout 每次导出都会写新 dump）
.\scripts\import-fmscout.ps1 -Watch -IntervalSeconds 15
```

也可以在「数据与诊断 → FMSuperScout 接入」里选文件预览/导入，或把 dump 直接拖到「上传扫描数据」（后端自动识别）。

适配报告会列出：映射了哪些字段、导出里根本没有的字段（出场时间、统计、转会、伤病、挂牌状态——相关功能保持
「不可用」）、以及被忽略的隐藏属性和原因。字段映射与安全边界见 [docs/FMSUPERSCOUT.md](docs/FMSUPERSCOUT.md)。

> 真实 FM27 导出尚未在本机核对：适配依据来自上游源码的字段定义。导入前先跑 `-Validate`（P0-1 审查报告），
> 它会给出字段覆盖率、唯一 ID、未知字段、版本兼容与最终结论；`-Validate` / `-Preview` 都不写库。
>
> 验收：`.\scripts\p0-handoff.ps1` 一条命令收齐审查报告、E2E 与读取器记录（输出到 `exports\p0-report-*`），
> 逐步操作见 [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)。

## 真实数据接入流程（自研读取器）

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
- **缺失即标注**：任一评分维度缺少输入时返回 `null` 与缺失原因，并按可用维度重新分配权重，绝不用 0 冒充观测值。
- **事实与推断分开**：AI 回答把数据库事实、模型计算、AI 推断与无法获得的数据分四类呈现，并给出工具级引用。
- **可追溯**：每次统计、估值、评分都带 `algorithm_version`、样本量、字段覆盖率。
- **本地优先**：API 只监听 `127.0.0.1`，可选 `X-ScoutMind-Token` 鉴权，CORS 仅允许本地来源。

## 测试

```powershell
# 后端（377 个用例：导入幂等、快照追加、身份复用、费用口径、统计/相似/估值、权限隔离、候选择确认、
#      阵容六维评分、球员六维评分、隐藏价值规则覆盖、成长速率、表现百分位、交易类型体系、AI 不编造、鉴权）
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
| `docs/FMSUPERSCOUT.md` | FMSuperScout 适配层：字段映射、状态/租借扩展、审查报告、三种导入方式、安全与许可证边界 |
| `docs/ACCEPTANCE.md` | P0-5 读取器验收与 P0-6 端到端验收清单，含「需要用户提供什么」 |
| `docs/MODELS.md` | 阵容/球员/发展/表现/成本模型的公式、权重与缺失数据处理 |
| `docs/DATA_MODEL.md` | V2 规格表名与实现表的映射、新增表说明 |
| `docs/SECURITY.md` | 本地鉴权、只读约束、数据与许可证边界 |
| `docs/ROADMAP.md` | 阶段划分、当前完成度、下一步 |

## 免责声明

ScoutMind 是玩家自用的数据分析工具，与 Sports Interactive / SEGA 无隶属或授权关系，不包含游戏本体、游戏素材或
他人存档。仅使用你自己机器上的存档与运行数据。代码采用 MIT 许可证；游戏数据、商标和素材的权利不随代码许可证
转移，商业化前必须单独审查。
