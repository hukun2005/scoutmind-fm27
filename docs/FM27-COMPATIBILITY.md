# FM27 兼容性事实源（唯一入口）

> 这份文档是**当前**状态的唯一说明。历史验收记录（`docs/acceptance/`, `docs/FM27-27.1-FIELD-VALIDATION.md`）
> 保留为当时快照，不随代码更新；两者冲突时以本文件 + 配置文件为准。

## 1. 三份配置与唯一事实源

| 文件 | 回答的问题 | 机器校验 |
| --- | --- | --- |
| `live-reader/ScoutMind.FMReader/Versioning/verified-versions.json` | 哪个 Build 允许扫描（版本闸门） | `Diag configcheck` |
| `live-reader/ScoutMind.FMReader/Versioning/compatibility-registry.json` | 字段级证据：Verified / Candidate | `Diag configcheck` |
| `config/compatibility.json` | 桌面端发布的兼容清单 | `GET /api/v1/compatibility` |

- 引擎启动与扫描前都会做交叉校验（`CompatibilityConfig.Validate()`），任何冲突 → 拒绝扫描。
- 后端 `GET /api/v1/compatibility/evidence` 返回合并视图（构建、字段证据、冲突列表）。
- 旧的 `GET /api/v1/compatibility` 也改为读取这套配置；数据库里的 `reader_compatibility`
  只作为历史记录，若与配置冲突会以 `stale_db_status` 报出来。

## 2. 当前版本矩阵

| Build | 布局 | 闸门状态 | 已核对字段 | 上游一致字段 |
| --- | --- | --- | --- | --- |
| 26620374 | FM27_1 | **verified**（允许扫描） | 11 | 7 |
| 26577676 | FM27_0 | candidate（拒绝扫描） | 0 | 0 |

- AppId：4530370（FM27）；插件：27.1.0+2505117。
- 未登记 Build：一律拒绝扫描，不存在 `--force`。

## 3. 字段状态分层

| 状态 | 含义 | 来源 |
| --- | --- | --- |
| Verified | 已在游戏界面核对一致 | `verified_fields` |
| Candidate | 与上游/导出逐字段一致，但未在 UI 核对 | `upstream_agreement_fields` |
| Pending | 布局里有、尚无证据 | 布局定义 |
| Failed | 核对失败 | 诊断报告 |
| NotSupported | 该版本不提供 | 布局/诊断 |

**整体允许扫描 ≠ 所有字段 Verified。** 例如 CA/PA 在游戏 UI 中不可见，永远不会是 Verified；
身高（`PLAO_HEIGHT`）因 31/48,089 与参考导出有 1–6 cm 差异，保持 Candidate。

## 4. 真实验收记录

| 日期 | Build | 结果 | 记录 |
| --- | --- | --- | --- |
| 2026-11-19 | 26620374 | 50,839 球员，两次扫描一致 | `docs/acceptance/VERIFY-2026-11-19-EVENING.md` |
| 2026-11-20 | 26620374 | 50,365 球员，两次扫描零差异，导入成功 | `docs/acceptance/VERIFY-2026-11-20-PHASE1.md` |

## 5. 如何复核

```bash
# 读取器侧：三份配置是否一致（不一致退出码 3）
live-reader/tools/ScoutMind.FMReader.Diag/bin/Release/net10.0/ScoutMind.FMReader.Diag.exe configcheck

# 后端侧：合并视图与冲突
curl http://127.0.0.1:8000/api/v1/compatibility/evidence
```

## 6. 变更规则

1. 新增 Build：先加注册表（字段证据），再加闸门条目，最后 `configcheck` 通过。
2. 提升字段状态必须附证据（UI 截图/导出对比），不允许"整体允许扫描"顺带升级字段。
3. 历史验收文档不覆盖，只追加新记录。
