# V3.2.9 前端身份审核中心

## 1. 复用与新增

- 现有前端为 Vue 3 + Element Plus + vue-router；没有重建路由体系。
- 新增页面：`frontend/src/views/PlayerIdentityCenterView.vue`，路由 `/identity-center`，导航项「球员身份中心」。
- 复用组件：`PageHeader`、`KpiCard`、`SectionCard`、`EmptyState`。
- 新增 API 模块：`frontend/src/api/identityCenter.ts`；类型：`frontend/src/types/identityCenter.ts`。
- 原有「身份复核」页（同 UID 冲突）保持不动，两页职责区分：旧页处理 V3.2.8 冲突，新页处理全库 UID 作用域与审核队列。

## 2. 页面能力

1. 全库统计：球员实例、唯一 UID、重复 UID、待审核、人工确认关联。
2. 全库扫描：输入 `scan_id` 与批大小，展示批次状态与计数、错误码。
3. 批次控制：暂停 / 恢复 / 取消。
4. 审核队列：按状态与类型筛选，展示类型、UID、原因、状态、时间。
5. 条目详情：实例列表、原始 payload、处理备注、四种人工决定。
6. 审核历史：时间、决定、备注。
7. 跨存档候选：指定另一个存档生成候选，展示姓名、生日、匹配度、UID 是否相同（仅证据）。

## 3. 安全约束

- 前端不能提交 `Verified`：后端对 payload 中的 `verification_status` / `status = Verified` 直接拒绝（`VERIFIED_NOT_SETTABLE`）。
- 所有决定都走后端审核服务并写审计表。
- 页面只展示当前存档数据；跨存档查询需要显式传入属于当前用户的存档 id。

## 4. 构建验证

```
cd frontend && npm run build
```

结果：**PASS**。`vue-tsc --noEmit` 通过，产物包含 `PlayerIdentityCenterView-*.js`（约 10.4 kB）。

## 5. 未执行

- 浏览器端 E2E（Playwright）未在本阶段执行：NOT_RUN。
- 真实数据下的视觉验收：NOT_RUN（依赖真实扫描结果）。
