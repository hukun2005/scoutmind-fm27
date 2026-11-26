# Verified 门控报告（VERIFIED-GATE-REPORT）

- 运行日期：2026-11-25
- 游戏版本：FM27 27.1
- Steam Build：26620374
- DLL 版本：game_plugin.dll 27.1
- Git SHA：`5720c88`（报告整理时；门控修复为 `7f56e67`）
- 详细记录：`PERSON-VERIFICATION-GATE.md`、`PERSON-VERIFICATION-RESULTS.md`、`HUMAN-VERIFICATION-SHEET.md`
- 审计日志：`person-verification-audit-2026-11-25.jsonl`

## 1. 门控条件

Mark(Verified) 必须同时满足：

1. 构建号与布局版本匹配。
2. Person 指针有效。
3. 结构校验通过。
4. 姓名可读。
5. 生日可读，或存在经批准的替代策略。
6. 属性记录唯一关联。
7. 无多候选、无身份冲突。
8. 重复读取稳定。
9. 人工确认，且 reviewer / source / evidence 齐全。
10. 只记录已验证字段，不把 CA/PA 等界面不可见字段算作已验证。

任一条件不满足时只能停留在 `HumanReviewPending`、`StructurallyValid`、`Conflicted`、`Unstable`、`UnsupportedBuild` 或 `Rejected`。

## 2. 真实人工核对结果

| 球员 | 出生日期 | 俱乐部 | UID | 已验证字段 | 状态 |
| --- | --- | --- | --- | --- | --- |
| Erick Pulgar | 1994-01-15 | 弗拉门戈竞赛会 | 75030706 | 姓名、生日、俱乐部、UID | Verified |
| Georginio Wijnaldum | 1990-11-11 | 伊蒂哈德足球俱乐部 | 859612 | 姓名、生日、俱乐部、UID | Verified |
| Wang Junyang | 2007-10-02 | 陕西联合 | 2000381482 | 姓名、生日、俱乐部、UID | Verified |

- 3 次运行退出码均为 0，`mark_verified = true`，冲突 0。
- CA（134 / 135 / 50）仅作为证据记录，未计入已验证字段。
- 另有 1 条历史 `HumanReviewPending`（Ahmed Rashid，旧存档状态），未 Mark。

## 3. 安全事件与纠正

- 早前按定位序号执行验证时，序号漂移导致 3 次验证指向了非人工确认的球员。
- 相关 3 条错误 Verified 审计与 JSON 已撤回；审计文件未保留错误记录。
- 修复 `7f56e67`：`verify --name --dob` 唯一选人，匹配 0 条或多条都拒绝执行。
- 该事件证明门控必须绑定可复现身份字段，不能绑定堆扫描序号。

## 4. 状态

| 项目 | 状态 |
| --- | --- |
| 无人确认不 Mark | PASS |
| 确认信息不完整不 Mark | PASS |
| 多候选/冲突不 Mark | PASS |
| 构建不匹配不 Mark | PASS |
| 重复确认不改变结果 | PASS |
| 旧版本候选重新确认被拒绝 | PASS |
| 真实 3 人 Verified | PASS |
| 全库 Verified 覆盖率 | PARTIAL（仅 3 人人工核对） |
| 存档切换后旧 Verified 的持续有效性 | UNKNOWN |

## 5. 未完成项

- 仅人工核对 3 名球员，未覆盖全库。
- 当前存档状态已变化，Phase 7 的 3 名球员在后续扫描中无法重新定位；审计仅反映当时存档状态。
- 未实现跨存档的 Verified 持久化与自动失效；存档切换后必须重新核对。
- 未对当前存档的 1 条同名冲突做人工裁定。
