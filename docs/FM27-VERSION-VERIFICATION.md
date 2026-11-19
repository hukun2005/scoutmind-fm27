# FM27 版本验证流程（原生读取引擎）

原生读取引擎能读到什么，取决于 **内存布局是否正确**。上游 FMSuperScout 的 FM27 布局是按
`game_plugin.dll 27.0.x` 钉的（`Fields.FM27.SupportedMinor = 0`），本机是 **27.1**（`27.1.0+2505117`），
所以当前状态是 `candidate`：**可以识别、可以拒绝，但不允许扫描**。

本文说明为什么不能"编译通过就宣称支持"，以及要把它变成 `verified` 需要做什么。

## 1. 两道闸门

| 闸门 | 位置 | 依据 | 拒绝时的表现 |
| --- | --- | --- | --- |
| 读取器兼容清单 | `config/compatibility.json` → `CompatibilityService` | `verified` 才允许进入 `Compatible` | 状态 `Unknown`，`probe`/`scan` 不执行 |
| 引擎版本闸门 | `live-reader/ScoutMind.FMReader/Versioning/verified-versions.json` | 构建号 + 插件主次版本，`verified` 才允许读内存 | `probe`/`scan` 返回失败并说明原因 |

两者独立：即使读取器清单把某构建标成 `verified`，引擎清单没标，仍然不会读内存。反之亦然。

## 2. 本机现状（2026-11-18）

```
游戏    appId=4530370  build=26620374  版本=27.1.0
插件    27.1.0+2505117（文件版本 27.1）
上游    FMSuperScout 1.7.3，Fields.FM27 支持 27.0
结论    candidate → 拒绝扫描
```

引擎诊断（`ScoutMind.FMReader.Diag status`）：

```
构建 26620374 未验证：本机 Steam 构建。上游 FMSuperScout 1.7.3 的 FM27 偏移是按 27.0 钉的
（Fields.FM27.SupportedMinor=0），本机是 27.1，偏移未逐类核对。
```

这不是缺陷，是设计：宁可拒绝，也不输出"看起来像真的"的错数据。

## 3. 变成 verified 需要做什么

按顺序做，每一步都要留下记录（写进 `verified-versions.json` 的 `evidence` 字段）。

### 3.1 逐类核对偏移

逐项对照游戏内界面与内存读出值，**两项都要记录**（期望值、实际值）：

| 对象 | 上游字段 | 核对方式 |
| --- | --- | --- |
| 球员 | `PLAO_CA` / `PLAO_PA` | 游戏内球员档案的 CA/PA；同一球员在两次扫描里应稳定 |
| 球员 | `PERO_DOB` | 出生日期 |
| 球员 | `PLAO_POSITIONS` | 位置（`posArr`） |
| 球员 | `PLAO_ATTRS`（55 字节） | 抽 5 个属性对照属性页 |
| 球员 | `PLAO_HEIGHT` | 身高 |
| 球员 | `PERO_NATION` / 姓名三个字段 | 姓名、国籍 |
| 合同 | `PERO_FULL_CONTRACT` | 合同到期日、周薪 |
| 俱乐部 | `Club` 对象、`clubRep` | 俱乐部名称、声誉 |
| 球队 | 球队对象 + 球员所属 | 球员当前俱乐部；预备队/青年队归属（上游只给整数 `teamType`，语义需自行确证） |

只要有一项对不上，就说明布局变了：不要"修一半"，按上游 `docs/repin-guide.md` 重新钉一组偏移，
并在 `Fields.cs` 里加一条新布局（ScoutMind 不改这个文件，改的是上游数据，走升级流程）。

### 3.2 真实存档回归

1. 启动 FM27，加载同一存档；
2. 连续扫描两次，`scan_id` 不同但**球员 id、CA/PA、合同**完全一致；
3. 用 ScoutMind 导入，检查 `players` 数量与游戏内数据库一致（允许合理差异，如职员/退役球员）；
4. 抽查 3 名球员的俱乐部归属与阵容层级；
5. 检查 `coverage`：`players`/`clubs`/`contracts` 为 true，`transfers`/`loans`/`team_tiers` 按实际能力为 false。

### 3.3 更新清单

在 `verified-versions.json` 增加：

```json
{
  "layout": "FM27",
  "app_id": "4530370",
  "build": "26620374",
  "plugin_version": "27.1.0+2505117",
  "status": "verified",
  "note": "27.1 布局已逐类核对（2026-11-xx）",
  "evidence": ["docs/verification/fm27-26620374.md"]
}
```

同时更新 `config/compatibility.json` 里对应条目的 `status`。两处都改完，读取器才会进入 `Compatible`，
`probe` 才会通过，`scan` 才会真正读内存。

## 4. 不能做的事

- 不能用"编译通过""单元测试通过"代替真实存档核对（这也是任务书明确禁止的）；
- 不能在未核对的情况下把 `candidate` 改成 `verified` 来"让流程走通"；
- 不能加 `--force` / `--unsafe` 之类的绕过开关；
- 不能因为读到了数值就认为正确：17.0 的偏移读到 21.0 的数据也会"成功"，所以必须对照游戏内界面。

## 5. 诊断命令

```powershell
# 引擎视角（不经读取器闸门，直接看引擎判断）
.\live-reader\tools\ScoutMind.FMReader.Diag\bin\Release\net10.0\ScoutMind.FMReader.Diag.exe status
... probe
... scan        # 只有 verified 才会真的读内存，否则返回失败原因

# 读取器视角（含兼容清单闸门）
.\publish\win-x64\ScoutMind.LiveReader.exe status
.\publish\win-x64\ScoutMind.LiveReader.exe probe --engine native
```

`scan` 成功时会把协议报文写到 `scan --output <目录>`，可用
`backend/app/api/routes_core.py::/imports/scan` 导入验证。

## 6. 自动化支持（2026-11-19 新增）

现在有工具链支撑上面第 3 节的人工核对，仍然**没有**任何绕过开关：

| 组件 | 作用 |
| --- | --- |
| `Layouts/FM27_0_Layout`、`FM27_1_Layout` | 27.0 与 27.1 的独立布局表，字段级状态 |
| `Layouts/LayoutResolver` | 构建号 → 布局；未登记构建返回 `null` |
| `Versioning/CompatibilityRegistry` | 构建 → 布局 + 已验证字段 + 证据（`compatibility-registry.json`） |
| `Engine/GameBuildDetector` | 进程/安装目录/插件版本/Steam 构建号 |
| `Probes/ObjectProbes` | 7 组只读探测：player / club / team / contract / loan / transfer / integrity |
| `Probes/ReportBuilder` | 汇总为 `Verified / Candidate / Rejected / Unknown` |
| `ScoutMind.FMReader.Diag report` | 生成 JSON 诊断报告，可归档为验证证据 |

判定规则：**结构自洽最多到 `Candidate`**；只有 `verified_fields` 覆盖全部必填字段、且所有适用探测通过，才是
`Verified`，`ScanAsync` 才会读内存。

诊断命令：

```powershell
$diag = ".\live-reader\tools\ScoutMind.FMReader.Diag\bin\Release\net10.0\ScoutMind.FMReader.Diag.exe"
& $diag layout                       # 构建 → 布局 → 注册状态
& $diag report .\exports\report.json # 完整诊断报告（含逐字段状态与探测明细）
& $diag probe                        # 只有 Verified 才会 passed=true
```

报告里的 `Probes[].Checks[]` 会列出每项检查的实际值与阈值（例如 `ca_range：32/32（100%，阈值 95%）`），
失败项直接给出原因，便于定位是哪一类偏移不对。
