# V3.2.9.2 阶段 7 — 真实 FM27 验证

- 执行时间：2026-11-26（Asia/Shanghai）
- 环境：FM27 进程 pid `72012`，构建 `26620374`，插件 `27.1`，布局 `FM27_1`
- 存档目录：`C:\Users\hukun\Documents\Sports Interactive\Football Manager 27\games`
  - `hu kun-北京国安.fm`
  - `hu kun-大连英博.fm`
  - `hu kun-利兹联.fm`
  - `hu kun-利兹联 (v02).fm`
  - `hu kun-利兹联 (v03).fm`
  - `last save overwrite backup.fm`
- 操作边界：只读取进程与存档文件元数据；未写入、未移动、未删除任何存档；
  诊断状态文件写在 `%TEMP%`，不影响用户真实状态。

## 1. 自动解析（未指定文件）

命令：

```powershell
dotnet run --project live-reader/ScoutMind.Reader -c Release -- `
  save-identity --diagnostics --json --state "$env:TEMP\v3292-real-state.json"
```

实测结果（退出码 `3`，失败关闭）：

```json
{
  "status": "discovered",
  "ambiguous": true,
  "snapshot_eligible": false,
  "generation": 1,
  "confirmation_invalidated": false,
  "verify_requested": false,
  "verify_applied": false
}
```

- 识别到 3 个带稳定元数据的候选存档；
- 无法唯一确定当前存档 → `AMBIGUOUS_SAVE_FILES`；
- 不给当前指纹、不允许 Verified。

**结论**：真实环境确实存在“多存档无法判定当前存档”的场景；本版本按安全语义返回歧义，
不再用历史确认反向选择（旧行为会在这里返回旧存档指纹）。

## 2. 显式指定文件

命令（对 `hu kun-利兹联.fm`）：

```powershell
dotnet run --project live-reader/ScoutMind.Reader -c Release -- `
  save-identity --save-file "...\hu kun-利兹联.fm" --verify --diagnostics --json `
  --state "$env:TEMP\v3292-real-state-explicit.json"
```

实测结果（退出码 `3`）：

```json
{
  "status": "candidate",
  "current_save_confirmed": false,
  "limitations": ["CURRENT_SAVE_UNCONFIRMED"],
  "verify_applied": false,
  "generation": 1
}
```

诊断：

> `--verify 被拒绝：显式 --save-file 只能证明该文件自身的身份，不能证明它是当前加载存档（CURRENT_SAVE_UNCONFIRMED）。`

**结论**：显式路径不再能绕过身份校验，符合任务书 §5.4。

## 3. 真实 A/B/A 切档

### 3.1 协议

- A = `hu kun-利兹联.fm`，B = `hu kun-大连英博.fm`；
- 每一步都由用户在 FM27 客户端内**实际加载目标存档并保存一次**，用存档修改时间作独立佐证；
- 真实文件指纹用 `save-identity --save-file <原文件>` 采集；
- 状态机（确认/失效/generation）走**自动路径**：用 `SCOUTMIND_FM_SAVE_DIR` 指向只含当前存档副本的临时目录。
  原因：真实目录同时存在 5 个存档，自动解析必然 `AMBIGUOUS_SAVE_FILES`（见 §1），无法进入确认路径；
  受控目录只消除歧义，不改变文件身份计算逻辑。

### 3.2 操作与时间线

| 步骤 | 用户操作 | 目标文件修改时间 |
| --- | --- | --- |
| A1 | 加载利兹联并保存 | `2026-11-26 16:24:29`（起点）→ 回到 A 前 |
| B1 | 加载大连英博并保存 | `2026-11-26 19:19:59` |
| A2 | 重新加载利兹联并保存 | `2026-11-26 19:20:49` |

时间顺序证明 B1 → A2 的操作确实发生（A2 为最新）。

### 3.3 结果

真实文件指纹（`--save-file`，状态均为 `CANDIDATE + CURRENT_SAVE_UNCONFIRMED`）：

| 步骤 | 指纹 |
| --- | --- |
| A1 | `si:v1:file:9718fb6a26c855c4f657897c6f186d9532e739f0caa14e3a3165ff1b2235057b` |
| B1 | `si:v1:file:368750cb08fca0946b06f5686c6edc6ec2e2039f0f739703cef8efd9cbe6136f` |
| A2 | `si:v1:file:e973de425b90a87efb4f80b9fcdda7beb1746dd66198f8cb230e99dcd75fb44a` |

- A1 ≠ B1：切档后是可区分的不同存档；
- A2 ≠ A1：**游戏内保存会替换文件，FileId 变化**（既有设计限制，见 §4）；
  因此真实文件层不能直接比较 A1/A2 指纹，必须依赖状态机的“变化即失效 + 重新确认”语义。

状态机（自动路径，共享状态文件）：

| 步骤 | status | generation | confirmation_invalidated | verify_applied | 指纹 |
| --- | --- | --- | --- | --- | --- |
| A1 | verified | 1 | false | true | `…0193ae6cea` |
| B1 | verified | 2 | **true** | true | `…d7dddc23` |
| A2 | verified | 3 | **true** | true | `…0193ae6cea` |

诊断原文（B1）：

> 检测到当前存档已变化（确认 880193ae6cea → 当前 8eb8d7dddc23）：旧确认与依赖旧存档的 Verified 立即失效。

诊断原文（A2）：

> 检测到当前存档已变化（确认 8eb8d7dddc23 → 当前 880193ae6cea）：旧确认与依赖旧存档的 Verified 立即失效。

最终状态文件：`status=Verified`、`generation=3`、`userConfirmedFingerprint` 为 A 的指纹。

### 3.4 结论

| 验收点 | 结果 |
| --- | --- |
| 切档后不返回旧存档指纹 | PASS |
| 切档使旧确认立即失效 | PASS（B1、A2 均为 `true`） |
| generation 随切档递增 | PASS（1→2→3） |
| 返回 A 后重新确认到 A | PASS（状态机指纹 A1 == A2） |
| 真实文件 A/B 可区分 | PASS（A1 ≠ B1） |
| 自动识别“当前加载存档” | 仍为 `AMBIGUOUS_SAVE_FILES`（多存档环境，未变） |

**验收范围说明**：本项验证的是“真实存档文件 + 真实切档操作下的身份失效与重新确认”；
当前存档由操作者在游戏内切换并以保存时间为佐证，工具本身仍不声称能自动识别多存档环境下的当前存档。

## 4. 当前限制声明

- 当存档目录同时存在多个存档且没有任何文件被进程独占锁定时，系统返回
  `AMBIGUOUS_SAVE_FILES`，不会声称已完成“进程 ↔ 存档”绑定。
- 当只有一个候选文件时，系统按唯一文件解析，标记 `CurrentSaveConfirmed=true`，
  但仍缺少游戏内 `SAVE_ID / WORLD_ID`，最高只能到 `CANDIDATE`。
- 游戏内保存会替换存档文件，`FileId` 随之变化 → 真实文件指纹变化 → 必须重新确认；
  这是 fail-closed 的既有设计，不是缺陷。
- 真实目录有 5 个存档时自动解析保持 `AMBIGUOUS_SAVE_FILES`；A/B/A 的状态机验证使用
  `SCOUTMIND_FM_SAVE_DIR` 指向仅含当前存档副本的临时目录，未修改任何原始存档。
- 因此本版本的能力边界是：
  - **不发生错误 Verified / 不跨存档复用旧指纹**：已实现并有测试与真实读取证据；
  - **进程与存档的强绑定**：在无法获得运行时证据时明确标记未确认，不宣称完成。
