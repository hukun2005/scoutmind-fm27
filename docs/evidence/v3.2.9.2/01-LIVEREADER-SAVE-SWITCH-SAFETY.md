# V3.2.9.2 阶段 1 — LiveReader 存档切换安全

- 分支：`feature/v3.2.9.2-livereader-save-switch-safety`
- 基线：`main@24beaba`
- 范围：只读游戏/存档；未修改任何已发布 migration；未删除任何测试。

## 1. 问题

基线里 `SaveIdentityResolver.Resolve()` 在“多存档且无法判断谁被占用”时，会拿
`UserConfirmedFingerprint` 在候选文件里**反向选择**当前存档。切档后如果新存档没有被
FM27 独占锁定，解析器仍会命中旧文件，`save-identity` 继续输出旧指纹，Person Verify
也就继续沿用旧存档身份。

## 2. 修改

### 2.1 选择与校验分离

`live-reader/ScoutMind.FMReader/Discovery/SaveIdentityModels.cs`

- `Resolve()` 不再用确认指纹消歧；选择当前存档只依据运行时证据（被占用 / 唯一文件）。
- `SaveIdentityResolution` 新增：
  - `CurrentSaveConfirmed`：是否具备“这就是当前加载存档”的运行时证据；
  - `LimitationCodes`：限制原因（`AMBIGUOUS_SAVE_FILES`、`NO_SAVE_FILE`、
    `UNSTABLE_SAVE_FILE_IDENTITY`、`CURRENT_SAVE_UNCONFIRMED`）。
- 歧义、无文件、元数据不稳定一律 `CurrentSaveConfirmed=false` 且 `SnapshotEligible=false`。

### 2.2 显式 `--save-file` 不再能升级为 Verified

`SaveIdentityInput.ExplicitFileSelection` 为真时：

- 只保留文件身份指纹，状态最高 `CANDIDATE`；
- 返回 `CURRENT_SAVE_UNCONFIRMED`；
- `--verify` 被拒绝，并给出明确诊断。

`live-reader/ScoutMind.FMReader/Discovery/SaveIdentityBinding.cs` 的
`CurrentFingerprint()` 现在要求 `CurrentSaveConfirmed`。因此 Person Verified 门控
拿不到“显式路径”的指纹，无法被绕过。

### 2.3 旧确认 / 旧会话失效 + generation

`live-reader/ScoutMind.FMReader/Engine/FmSaveIdentityDiagnostics.cs`

1. 先用纯运行时证据解析当前存档；
2. 若当前指纹 ≠ 已确认指纹 → 立即清空确认、`ConfirmationInvalidated=true`、generation+1；
3. 会话键变化（进程重启/新会话）→ generation+1；
4. 仍有效的确认只作为“校验证据”参与第二次解析；
5. 结果与 generation 一起持久化。

`SaveIdentityStore` 增加 `Generation` 字段（缺失时按 0 读取，兼容旧状态文件）。

### 2.4 CLI 可观测性

`live-reader/ScoutMind.Reader/Cli.cs` 的 `save-identity` 输出新增：
`generation`、`confirmation_invalidated`、`identity.current_save_confirmed`、
`identity.limitations`；文本输出同步显示。

## 3. 新增测试（12 项）

`live-reader/tests/ScoutMind.FMReader.Tests/LiveReaderSaveSwitchSafetyTests.cs`

| 用例 | 断言 |
| --- | --- |
| 切档检测 | 指纹变化、generation 递增、旧确认被清空 |
| 绝不复用旧指纹 | 当前指纹 ≠ 旧确认指纹 |
| 旧 Verified 失效 | 新存档未确认前只能是 CANDIDATE，且不可快照 |
| 多候选歧义 | 拒绝 `--verify`，无当前指纹，返回 `AMBIGUOUS_SAVE_FILES` |
| 未知当前存档 | 拒绝 `--verify`，无当前指纹 |
| 指纹不一致 | 旧确认失效并显式报告 |
| 进程重启 | generation 递增，但不误判为切档 |
| 显式文件 | 最高 CANDIDATE，`CURRENT_SAVE_UNCONFIRMED`，不给门控 |
| 显式文件缺失 | 失败关闭，单文件探测返回空 |
| 文件被替换（FileId 变化） | 旧确认失效 |
| 多存档 | 不得静默选择第一个 |

同时把基线中“多存档时用旧确认消歧”的旧断言改写为**安全语义断言**（测试名称与断言都已加强，未删除测试）。

## 4. 实际结果

命令：

```powershell
dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests -c Release
```

结果：`PASS 333 · FAIL 0`（基线 311 + 阶段 1 新增 12 + 阶段 2 新增 10）。

## 5. 限制

- 当 FM27 与存档文件都不提供“当前加载文件”的运行时证据时，本机仍只能给
  `CURRENT_SAVE_UNCONFIRMED`，不会声称已完成进程与存档的完全绑定（符合任务书 §5.4）。
- `--save-file` 现在明确是“定位信息”，不再能独立完成 Verified。
