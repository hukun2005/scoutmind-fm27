# ScoutMind Live Reader（实时读取器）架构与使用说明

本文档描述 Phase 1 的 Windows/C# 部分：**检测 + 版本闸门 + 一次扫描 + 原始导出**。
本阶段不连接数据库、不做解析入库；解析与入库属于后端职责（见 `docs/API.md` 与 `docs/DATA_PROTOCOL.md`）。

> **必须知道的事实**：本机（开发机）**没有验证过任何一次真实的 FM27 扫描**。
> `config/compatibility.json` 中只有一条 `candidate` 条目，读取器因此会拒绝读取。
> 只有把该条目改名为 `verified` 并填写 `verifiedAt` 之后，读取器才会进入 `Compatible`。

---

## 1. 设计原则

1. **只读**：读取器只读注册表、Steam 文本清单、文件版本资源；不写入、不注入、不 hook 游戏进程。
2. **严格版本闸门**：不匹配就拒绝，绝不"猜一个接近的版本"。未知构建永远不借用旧版本偏移量。
3. **不伪造数据**：缺失字段保持 `null`，绝不补默认值；扫描器没给的字段不会出现在信封里。
4. **失败即拒绝**：`Unknown` / `Unsupported` / `ProbeFailed` 是终态，任何读取动作都被拒绝。
5. **诊断优先**：每一步失败都记录可读的中文原因，便于排错。

---

## 2. 架构

```
ScoutMind.Agent（可选）
      │  1. 启动 reader CLI，透传参数与退出码
      ▼
ScoutMind.LiveReader.exe
      │
      ├─ SteamLocator ──► 注册表 HKCU\Software\Valve\Steam\SteamPath
      │                   steamapps\libraryfolders.vdf
      │                   steamapps\appmanifest_4530370.acf → buildid / installdir
      ├─ ProcessDetector ─► fm.exe（校验文件名与 ProductName）
      ├─ PluginProbe ─────► game_plugin.dll 的 ProductVersion（只读文件版本资源）
      ├─ CompatibilityService ─► compatibility.json 三方匹配
      ├─ StateMachine ────► 显式迁移，非法迁移抛异常
      └─ ScannerAdapter ──► 外部扫描器进程（stdout 协议 JSON）
                              │
                              ▼
                         ScanWriter → scan-<id>.json + scan-<id>.meta.json
```

组件职责：

| 组件 | 职责 | 关键约束 |
| --- | --- | --- |
| `SteamLocator` | 定位 FM27 安装、解析构建号 | 缺失/损坏只返回 `null` + 诊断，绝不抛异常 |
| `ProcessDetector` | 识别运行中的 FM27 | 主模块必须以 `fm.exe` 结尾，`ProductName` 含 `Football Manager`，否则跳过 |
| `PluginProbe` | 读取插件版本 | 只读文件版本资源，**不加载 DLL** |
| `CompatibilityService` | 版本闸门 | 三方全匹配 + `verified` 才算兼容 |
| `StateMachine` | 状态迁移 | 允许边表固定，非法迁移抛 `InvalidStateTransitionException` |
| `ScannerAdapter` | 外部进程编排 | 状态校验 → 启动 → 超时终止进程树 → 协议校验 |
| `ScanWriter` | 落盘 | 信封 camelCase；边车记录退出码与诊断 |
| `ScanProtocolSerializer` | 线上形态转换 | camelCase → snake_case（只改键名） |

### 2.1 检测细节

**Steam 定位顺序**

1. `HKCU\Software\Valve\Steam\SteamPath`
2. `HKLM\SOFTWARE\WOW6432Node\Valve\Steam\InstallPath`
3. `HKLM\SOFTWARE\Valve\Steam\InstallPath`

拿到 Steam 根目录后读取 `steamapps\libraryfolders.vdf`（新旧两种格式都支持），
依次在每个库中查找 `steamapps\appmanifest_4530370.acf`。

**插件定位顺序**（安装目录内，按序取第一个存在的）

1. `game_plugin.dll`
2. `fm_Data\Plugins\x86_64\game_plugin.dll`（当前 FM27 实际发布布局）
3. `fm_Data\Plugins\game_plugin.dll`
4. `Plugins\x86_64\game_plugin.dll`

**游戏版本派生**：取插件产品版本 `+` 之前的部分（`27.1.0+2505117` → `27.1.0`）。
拿不到插件版本时 `gameVersion` 为 `null`，不会猜测。

---

## 3. 状态机

```
NotFound ──► Detected ──► VersionIdentified ──► Compatible ──► ProbePassed ──► ScanCompleted
                 │                │                  │               │
                 ├──► Unknown     ├──► Unknown       ├──► ProbeFailed └──► ProbeFailed
                 └──► Unsupported └──► Unsupported   └──► Unsupported
```

允许边表（其余迁移一律拒绝）：

| 当前状态 | 允许迁移到 |
| --- | --- |
| `NotFound` | `Detected` |
| `Detected` | `VersionIdentified`、`Unknown`、`Unsupported` |
| `VersionIdentified` | `Compatible`、`Unknown`、`Unsupported` |
| `Compatible` | `ProbePassed`、`ProbeFailed`、`Unsupported` |
| `ProbePassed` | `ScanCompleted`、`ProbeFailed` |
| `ScanCompleted` / `Unknown` / `Unsupported` / `ProbeFailed` | 无（终态） |

失败状态（`Unknown`、`Unsupported`、`ProbeFailed`）**禁止任何后续读取**。
`ScanResult.state` 只会是 `ScanCompleted` 或 `ProbeFailed`。

---

## 4. 命令与退出码

### 4.1 读取器 `ScoutMind.LiveReader.exe`

```powershell
ScoutMind.LiveReader.exe status [--json]
ScoutMind.LiveReader.exe probe [--json]
ScoutMind.LiveReader.exe scan [--output <目录>] [--timeout <秒>] [--json]
ScoutMind.LiveReader.exe compatibility list [--json]
ScoutMind.LiveReader.exe --help
```

| 退出码 | 含义 | 典型触发 |
| --- | --- | --- |
| 0 | 成功 | `status` 到达 `Compatible` 及以上 |
| 2 | 未找到 FM27 | Steam 与进程都不存在 |
| 3 | 不支持或未知 | 构建未收录、插件版本不符、清单只有候选条目 |
| 4 | probe 失败 | 扫描器自检非零退出、超时 |
| 5 | 扫描失败 | 扫描器崩溃/超时/输出不是合法协议 JSON/落盘失败 |
| 64 | 用法或配置错误 | 未知参数、未配置扫描器、兼容清单不可用 |
| 130 | 用户取消 | Ctrl+C |

`scan` 的执行顺序是：检测 → （若为 `Compatible`）自动 probe → `ProbePassed` → 扫描。
**当前进程内**的 probe 失败不会被上一次运行的结果"继承"。

### 4.2 桌面代理 `ScoutMind.Agent.exe`

```powershell
ScoutMind.Agent.exe status [--json]
ScoutMind.Agent.exe scan [--sync] [--json]
ScoutMind.Agent.exe watch --interval-minutes <分钟>
ScoutMind.Agent.exe sync [--file <路径>]
ScoutMind.Agent.exe config show
```

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 2 / 3 / 4 / 5 | 原样透传读取器退出码 |
| 6 | 后端同步失败（扫描结果已进本地队列） |
| 64 | 用法错误 |
| 65 | 配置错误（找不到读取器、`agent.json` 非法） |
| 130 | 用户取消 |

代理**从不编造扫描结果**：读取器失败时它把读取器的退出码与 stderr 原样返回。

---

## 5. 配置外部扫描器（`scanner.json`）

读取器本身不含任何内存读取逻辑，扫描工作全部交给外部可执行文件。
把 `config/scanner.sample.json` 复制为可执行文件同目录的 `scanner.json`：

```json
{
  "scannerPath": "C:\\Tools\\ScoutMindScanner\\scoutmind-scanner.exe",
  "probeArguments": ["probe", "--read-only"],
  "scanArgumentsTemplate": "--scan --output \"{output}\" --save \"{saveName}\"",
  "timeoutSeconds": 120,
  "backendBaseUrl": "http://127.0.0.1:8000/api/v1",
  "apiToken": "",
  "saveName": "默认存档"
}
```

| 字段 | 说明 |
| --- | --- |
| `scannerPath` | 扫描器可执行文件绝对路径；为空则 `probe`/`scan` 直接以 64 拒绝 |
| `probeArguments` | probe 参数数组，逐项传递，不经过 shell |
| `scanArgumentsTemplate` | 扫描参数模板，按引号规则切分为多个参数 |
| `timeoutSeconds` | 默认超时；`--timeout` 可覆盖 |
| `backendBaseUrl` / `apiToken` / `saveName` | 代理与模板占位符使用；读取器本身不使用 |

模板占位符：`{output}`（输出目录）、`{scanId}`（本次尝试 ID）、`{saveName}`。

### 5.1 扫描器协议要求（对第三方程序的契约）

1. **只读**：必须只读访问游戏进程，禁止写入、注入、修改内存或存档。
2. **stdout 输出扫描协议 JSON**：根节点是对象，含 `schema_version`（字符串）与 `players`（数组）。
   缺任一项，读取器判为 `ProbeFailed`，不会落盘。
3. **退出码**：成功退出 0；任何非零退出码都视为失败，stderr 会被截断记录。
4. **超时**：超过超时时间，读取器会终止**整棵进程树**。
5. 建议同时输出 `game`、`scan`、`coverage`、`warnings`、`clubs`、`transfers` 字段，字段名同时接受
   snake_case 与 camelCase。

最小可接受输出示例：

```json
{
  "schema_version": "1.0",
  "players": [],
  "transfers": []
}
```

若扫描器不提供 `scan.scan_id`，读取器会生成一个 GUID 并在 `warnings` 中说明；
若提供但不是 ISO-8601，读取器会失败而不是伪造时间。

---

## 6. 扫描产物与协议转换

输出目录（默认 `<exe 目录>/scans`）中：

| 文件 | 内容 |
| --- | --- |
| `scan-<scanId>.json` | 扫描信封，camelCase（`schemaVersion`、`readerVersion`、`scan.scanId` …） |
| `scan-<scanId>.meta.json` | 边车：退出码、耗时、球会/球员计数、告警、诊断 |
| `scan-<attemptId>.stdout.txt` | 扫描器 stdout 原文 |
| `scan-<attemptId>.stderr.txt` | 扫描器 stderr 原文 |

`scanId` 来自扫描器（幂等键）；`attemptId` 是读取器本次运行的 GUID，用于文件命名，两者都记录在边车里。

上游后端要求 snake_case（`docs/DATA_PROTOCOL.md`），因此代理上传前调用
`ScanProtocolSerializer.ToProtocolJson`：只转换键名（`schemaVersion`→`schema_version`、
`game.appId`→`game.app_id`、`scan.scanId`→`scan.scan_id` …），字段值一字不改。

---

## 7. 桌面代理

`agent.json`（与 `ScoutMind.Agent.exe` 同目录，可选）：

```json
{
  "readerPath": "C:\\ScoutMind\\ScoutMind.LiveReader.exe",
  "scannerPath": "C:\\Tools\\ScoutMindScanner\\scoutmind-scanner.exe",
  "probeArguments": ["probe"],
  "scanArgumentsTemplate": "--scan --output \"{output}\"",
  "timeoutSeconds": 120,
  "backendBaseUrl": "http://127.0.0.1:8000/api/v1",
  "apiToken": "",
  "saveName": "默认存档",
  "queueDirectory": "queue"
}
```

- `readerPath` 省略时按顺序尝试：环境变量 `SCOUTMIND_READER_PATH` → 同目录
  `ScoutMind.LiveReader.exe` → 同目录 `ScoutMind.LiveReader.dll`（开发期通过 `dotnet` 启动）。
- 队列目录结构：`scans/`（读取器输出）、`pending/`（同步失败待重试）、`sent/`（已同步归档）。
- 后端同步：`POST {backendBaseUrl}/imports/scan`，配置 Token 时附带 `X-ScoutMind-Token` 头。
  只在**传输层失败**时重试一次；HTTP 4xx/5xx 不重试，避免重复提交。
  后端按 `scan_id` 幂等，`duplicate=true` 会被识别并提示。

环境变量：`SCOUTMIND_AGENT_CONFIG`、`SCOUTMIND_READER_PATH`、`SCOUTMIND_BACKEND_URL`、`SCOUTMIND_API_TOKEN`。

---

## 8. 发布

```powershell
pwsh -File scripts/publish-windows.ps1
```

产出 `publish/win-x64/`：

```
ScoutMind.LiveReader.exe    # 自包含单文件
ScoutMind.Agent.exe         # 自包含单文件
compatibility.json
scanner.sample.json
```

两个 exe 在同一目录，代理默认把同目录的读取器当作 `readerPath`。

---

## 9. 安全规则（必须遵守）

1. 绝不写入游戏进程内存、绝不注入 DLL、绝不 hook。
2. 只读访问：注册表读、文本文件读、文件版本资源读、进程元数据读。
3. 版本不匹配就拒绝；不提供"强制读取"开关。
4. 不把候选条目当作已验证条目；`candidate` 只给出 `Unknown`。
5. 外部扫描器是第三方程序，必须单独审查与授权，不得随本仓库分发。
6. 诊断信息可能包含本机路径，上传日志前请自行脱敏。

---

## 10. 本机实测记录（Phase 1）

开发机（Windows，Steam 库 `D:\steam`）实测：

| 项目 | 观测值 |
| --- | --- |
| Steam 注册表 | 可读 |
| 安装清单 | `D:\steam\steamapps\appmanifest_4530370.acf` |
| `buildid` | `26620374` |
| 安装目录 | `D:\steam\steamapps\common\Football Manager 27` |
| 插件 | `fm_Data\Plugins\x86_64\game_plugin.dll`，产品版本 `27.1.0+2505117` |
| 游戏进程 | 未运行（`fm.exe` 未启动） |
| 兼容清单条目 | `buildId=26577676`、`plugin=27.0.1+2503222`、`status=candidate` |

结论：构建号与插件版本都与清单不一致 → 状态 `Unsupported`，退出码 3，**拒绝读取**。
这正是版本闸门应有的行为，也说明**尚未验证真实扫描**。

---

## 11. 已知限制

- 本仓库不包含任何内存偏移量、AOB 扫描或读取实现；这些完全由第三方扫描器提供。
- 第三方扫描器需要单独审查、单独授权，其许可证与合规风险由使用者承担。
- `compatibility.json` 目前只有一条未验证的 `candidate` 条目。
- 尚未在本机跑通一次真实 `probe` + `scan`；参考扫描器的行为未经验证。
- 未实现存档解析、数据库写入、数据清洗；这些属于后续阶段。
- 读取器只处理单实例单存档；多存档并发未做验证。
- `status` 在游戏未运行时仍可判定版本，但 `probe` / `scan` 需要游戏保持运行（由扫描器决定）。

---

## 12. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `status` 退出码 2 | 没有 Steam 清单也没有进程 | 确认已通过 Steam 安装 FM27 |
| `status` 退出码 3，提示"未收录的构建" | 构建号不在清单 | 在清单中新增条目，先标 `candidate`，本机验证后再标 `verified` |
| `status` 退出码 3，提示"无法读取 game_plugin.dll" | 插件缺失或版本资源不可读 | 确认安装完整性；检查插件路径 |
| `probe` 退出码 64 | 没有 `scanner.json` 或路径不存在 | 复制 `scanner.sample.json` 并填写 `scannerPath` |
| `probe` 退出码 4 | 扫描器自检失败/超时 | 查看 `%TEMP%\scoutmind\probe-*` 的捕获文件与 stderr |
| `scan` 退出码 5 | 扫描器输出不是协议 JSON | 确认扫描器把 JSON 写到 stdout，且含 `schema_version` 与 `players` |
| 代理退出码 6 | 后端不可达或鉴权失败 | 检查 `backendBaseUrl` / `apiToken`；结果已进 `pending/`，稍后 `sync` 重试 |
