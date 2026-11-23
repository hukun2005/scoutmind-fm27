# ScoutMind FM27 V3.2.2.6 — 对象分类报告

- 分支：`codex/v3.2.2.3-date-discovery`（V3.2.2.6 工作分支）
- 真实 FM27：pid 105040，build 26620374，plugin 27.1
- 探测：71 个去重对象；57 个合法 UID；14 个 `0xFFFFFFFF`

## 1. 14 个哨兵对象

| # | 姓名 | CA | PA | 出生日期 | 合同指针 | 球队/俱乐部 |
|---|---|---:|---:|---|---|---|
| 1 | Óscar Trejo | 122 | 142 | 1988-117 | 0 / 空 | 无 |
| 2 | Necip Uysal | 110 | 125 | 1991-024 | 0 / 空 | 无 |
| 3 | Roberto Torres | 108 | 145 | 1989-066 | 0 / 空 | 无 |
| 4 | Asdrúbal | 88 | 122 | 1991-072 | 0 / 空 | 无 |
| 5 | Emilio Cubo | 81 | 118 | 1992-004 | 0 / 空 | 无 |
| 6 | Diego Pousa | 65 | 79 | 1998-037 | 0 / 空 | 无 |
| 7 | Vladimír Weiss | 120 | 145 | 1989-334 | 0 / 空 | 无 |
| 8 | Juraj Kucka | 115 | 150 | 1987-057 | 0 / 空 | 无 |
| 9 | Andy Halliday | 99 | 121 | 1991-284 | 0 / 空 | 无 |
| 10 | Fraser Fyvie | 83 | 96 | 1993-086 | 0 / 空 | 无 |
| 11 | Derrick Williams | 114 | 125 | 1993-017 | 0 / 空 | 无 |
| 12 | Trevor Carson | 107 | 124 | 1988-065 | 0 / 空 | 无 |
| 13 | Kevin Koffi | 97 | 113 | 1986-176 | 0 / 空 | 无 |
| 14 | Alberto Masi | 83 | 122 | 1992-246 | 0 / 空 | 无 |

## 2. 共同特征

14 个对象全部满足：

- 姓名可读，是真实足球运动员姓名；
- CA 65–122，PA 79–150，处于球员范围；
- 出生日期可解码；
- 合同指针为 0；
- 球队/俱乐部关系不可达；
- `OBJ_DUNI` 地址可读，值为 `0xFFFFFFFF`；
- 同一对象重复读取稳定。

## 3. 分类结论

**FreeAgentPlayerCandidate / Unattached Player（自由球员/无合同球员）**

> 用户已于 2026-11-23 确认：这 14 人当前为自由球员/无合同球员。该确认只用于分类，不改变 OBJ_DUNI 95% 安全阈值。

支持证据：

- 球员属性与出生日期正常；
- 全部无合同、无球队；
- UID 为哨兵值，而不是重复或不可读。

反对证据/未知：

- ~~还没有用游戏界面逐一确认~~ 用户已确认 14 人为自由球员；
- 不排除其中有人是未加载合同对象；
- 没有证明 `0xFFFFFFFF` 是“未分配 UID”的官方语义。

因此最终分类为：

```text
ObjectType: FreeAgentPlayerCandidate
ClassificationStatus: Candidate
Confidence: Medium
```

不是 `FirstTeamPlayer`，也不应当作有 UID 的正式球员直接进入 Canonical。

## 4. 对 OBJ_DUNI 的结论

- `0xFFFFFFFF` 不是重复 UID；
- 14/71 是真实球员对象没有可用 UID；
- 95% 阈值不能降低；
- 不能静默删除 14 个对象；
- 需要为“无 UID 的自由球员候选”设计显式 Unresolved 身份策略，或者证明其不应进入正式扫描身份集合。

## 5. 状态

| 项目 | 状态 |
| --- | --- |
| 完整 JSON 输出 | PASS（71 条样本，14 条哨兵明细） |
| 哨兵对象分类 | **PARTIAL**（Candidate） |
| OBJ_DUNI 适用性 | **PARTIAL**（自由球员候选无 UID） |
| 95% 安全门禁 | 保持，probe 仍 FAIL |
| 完整扫描 | 仍被阻止 |
