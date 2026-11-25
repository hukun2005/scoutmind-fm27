# Phase 7：人工核对后的 Verified 记录（真实 FM27）

> 运行日期：2026-11-25 · 游戏：FM27 27.1 · 构建 26620374 · 插件 27.1
> 人工核对记录：`HUMAN-VERIFICATION-SHEET.md`
> 审计日志：`person-verification-audit-2026-11-25.jsonl`
> 单目标结果：`person-verify-erick-pulgar-2026-11-25.json`、`person-verify-georginio-wijnaldum-2026-11-25.json`、`person-verify-wang-junyang-2026-11-25.json`

## 1. 验证方式

- 用户在 FM27 游戏界面核对 3 名不同特征球员的姓名、出生日期、俱乐部，并明确确认“3 人一致”。
- 使用 `verify --name <姓名> --dob <yyyy-MM-dd>` 精确选人，避免堆扫描序号漂移。
- 匹配不到或匹配到多条记录时命令直接拒绝执行；不会自动挑选。
- 门控要求 `--human-confirmed + reviewer + source + evidence` 全部提供后才允许 Verified。

## 2. 结果

| 球员 | 出生日期 | 俱乐部 | UID | CA（仅记录） | 关联 | 已验证字段 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Erick Pulgar | 1994-01-15 | 弗拉门戈竞赛会 | 75030706 | 134 | SingleCandidate | 姓名、生日、俱乐部、UID | **Verified** |
| Georginio Wijnaldum | 1990-11-11 | 伊蒂哈德足球俱乐部 | 859612 | 135 | SingleCandidate | 姓名、生日、俱乐部、UID | **Verified** |
| Wang Junyang | 2007-10-02 | 陕西联合 | 2000381482 | 50 | SingleCandidate | 姓名、生日、俱乐部、UID | **Verified** |

- 3 次运行退出码均为 0，`mark_verified = true`。
- 冲突数均为 0；每次关联都唯一。
- CA 只作为证据记录，不在 `verified_fields` 中（游戏界面不可见，未人工核对）。

## 3. 审计日志

审计日志当前包含 4 条：

1. Ahmed Rashid：`HumanReviewPending`，`mark_verified = false`（早前样本，未人工确认）。
2. Erick Pulgar：`Verified`，确认人 user，来源 fm27-ui，证据引用 HUMAN-VERIFICATION-SHEET.md。
3. Georginio Wijnaldum：同上。
4. Wang Junyang：同上。

每条 Verified 审计都记录：时间、结果、候选标识、布局版本、构建号、球员身份、关联状态、置信度、已验证字段、阻塞原因、确认人/来源/证据引用。日志不含 Person 指针或完整内存地址。

## 4. 安全事件与纠正

- 早前一次按“定位序号”执行的验证发生在另一存档状态：序号漂移导致实际指向 Franco Oviedo、Love Arrhov、Pedro Henrique，而用户确认的是另外 3 人。
- 已撤回这 3 条错误 Verified 审计及对应 JSON，未保留错误记录。
- 修复：提交 `7f56e67` 增加 `--name/--dob` 唯一选人，匹配不唯一即拒绝。
- 该事件验证了门控的两个关键点：序号不能作为身份；人工确认必须绑定到可复现的身份字段。

## 5. 范围与限制

- 本次仅覆盖 3 名球员；其他候选仍为未验证或 HumanReviewPending，不因本次结果批量升级。
- Verified 依赖当前存档状态；存档更换后需重新核对，旧审计只反映当时状态。
- 俱乐部和 UID 参与交叉校验；CA 未纳入验证。
- 未写入存档、未修改内存保护属性、未注入 DLL。

## 6. 复现

```text
ScoutMind.FMReader.Diag.exe verify --name "Erick Pulgar" --dob 1994-01-15 ^
  --located 800 --reads 3 --human-confirmed --reviewer user --source fm27-ui ^
  --evidence docs/evidence/v3.2.8/HUMAN-VERIFICATION-SHEET.md
```

## 7. 测试

- ScoutMind.FMReader.Tests：281/281 PASS（与本次验证代码一致，提交 `7f56e67`）。
