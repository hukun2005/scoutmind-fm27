# ScoutMind FM27 V3 实施报告

- 仓库：`hukun2005/scoutmind-fm27`
- 分支：`codex/scoutmind-v3-upgrade`
- 基线：`main` @ `73dc939`（含 CI 构建修复）
- 本轮范围：**仅第一阶段 SM-010 / SM-011 / SM-012**
- 执行日期：2026-11-20
- 状态口径：`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN` / `BLOCKED`

## 一、总览

| 编号 | 任务 | 状态 | 提交 |
| --- | --- | --- | --- |
| SM-010 | 上传安全与资源保护加固 | PASS | 见下 |
| SM-011 | Identity Resolution Center | PASS（后端 + 前端构建；真实交互未人工点验） | 见下 |
| SM-012 | FM27.1 Reader 稳定性与字段质量 | PASS（10 次真实扫描完成；合同异常已定位未修复） | 见下 |
| SM-013 | 历史转会数据管道 | PARTIAL（管道 PASS；自动来源 BLOCKED） | 见下 |
| SM-014 | 职业轨迹 | PASS | 见下 |
| SM-015 | 俱乐部转会情报 | PASS | 见下 |
| SM-016 | 转会投资回报 | PASS（真实历史数据缺失，仅确定性样本） | 见下 |
| SM-017 | 转会决策模拟器 | PASS | 见下 |
| SM-018 | AI Sporting Director 2.0 | PARTIAL（工具与假客户端通过；真实 LLM 未联调） | 见下 |
| SM-019 | 球员成长预测 | PASS（回测在真实存档 NOT_RUN） | 见下 |
| SM-020 | 自动引援推荐 | PASS | 见下 |

## 二、SM-010 上传安全与资源保护加固

### 目标

把上传限制从"路由内检查"提升到 ASGI 接收层：不依赖 Content-Length，超限在资源持续增长前拒绝；
multipart 在解析过程中即受限；慢速/断开/异常路径都清理。

### 修改文件

- `backend/app/api/uploads.py`
- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/api/routes_core.py`（导入限流改为共享 `import_slot`）
- `backend/tests/test_sm010_upload_hardening.py`（新增）
- `backend/tests/test_sm_phase1.py`（旧的私有辅助测试改为真实 Request）

### 核心实现

1. **ASGI 层限制**：`BodySizeLimitMiddleware` 包装 `receive`，累计每个 `http.request` 的实际字节；
   超过 `max_request_bytes` 抛内部异常并返回 413。chunked（无 Content-Length）同样拦截。
2. **解析过程中限制**：`limited_receive()` 用于 `request.form()`，multipart 每读一块就计数；
   `max_part_size` 同时限制单个分片，避免超大文件先被 spool 到磁盘。
3. **统一 413**：文件数 / 字段数 / 分片大小超限统一映射为 413（`too_many_files` / `too_many_fields` / `field_too_large`），
   不再暴露 Starlette 的 400 `http_error`。
4. **慢速上传**：`max_upload_read_seconds`（默认 120 秒）对单块等待做超时，超时返回 408 `upload_stalled`。
5. **客户端断开**：`http.disconnect` 转为 400 `client_disconnected`，不会把半截报文当完整数据。
6. **临时文件**：`finally: await form.close()`；解析异常路径同样关闭。
7. **并发**：上传解析信号量与导入信号量都改为"按事件循环惰性创建"，避免跨事件循环复用导致
   `bound to a different event loop`（真实存在于多 TestClient / 应用重载场景）。

### 数据库变更

无。

### 新增测试（`backend/tests/test_sm010_upload_hardening.py`）

- ASGI 中间件拦截无 Content-Length 的 chunked 超大请求，并证明**超限后不再继续读取**；
- multipart 文件超限 → 413；
- 字段数量超限 → 413 `too_many_fields`；
- 单字段大小超限 → 413 `field_too_large`；
- 慢速上传 → 408；
- 客户端断开 → 400；
- 上传并发上限；
- 正常 JSON 导入不受影响；
- 旧测试改造：成功/缺少 file 两条路径都验证表单被关闭。

### 测试结果

- `tests/test_sm010_upload_hardening.py`：8 通过
- 后端全量：见"四、总回归"

### 未解决问题

- ASGI 中间件在"应用已经开始发送响应后再超限"的极端情况下可能无法再写 413；正常请求体读取都发生在响应之前，已有路由级兜底。
- 真实慢速网络（带宽限速）未在 CI 中模拟，仅做单元级延迟注入。

## 三、SM-011 Identity Resolution Center

### 目标

让身份冲突可查询、可复核、可审计；合并必须人工确认且不丢历史数据。

### 修改文件

后端：

- `backend/app/models.py`（新增 `IdentityConflictAction`）
- `backend/app/schemas.py`（`IdentityConflictResolve`）
- `backend/app/api/routes_identity.py`（新增）
- `backend/app/main.py`（注册路由）
- `backend/alembic/versions/a4d8e1f63c09_identity_conflict_actions.py`（新增）
- `backend/tests/test_sm011_identity_center.py`（新增）

前端：

- `frontend/src/types/identity.ts`（新增）
- `frontend/src/api/identity.ts`（新增）
- `frontend/src/views/IdentityResolutionView.vue`（新增）
- `frontend/src/router/index.ts`（`/identity`）
- `frontend/src/App.vue`（导航项"身份复核"）

### API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/identity/conflicts` | 状态/类型/置信度筛选，分页、排序，返回 open/resolved/deferred 计数 |
| GET | `/api/v1/identity/conflicts/{id}` | 双方球员（姓名/生日/国籍/实例/快照/转会/来源）、证据、建议、操作历史 |
| POST | `/api/v1/identity/conflicts/{id}/resolve` | `same`（合并）/ `different` / `defer` |

### 核心实现

1. **权限**：冲突只能由所属存档的拥有者查看/处理；跨存档统一 404，不泄露存在性。
2. **合并（same）**：事务内把被合并身份的 `PlayerInstance` 改指向保留身份，`IdentityMatch` 一并迁移；
   `Player` 行保留（冲突证据、审计和外键仍引用它），因此**永不删除证据**；快照与转会的实例 id 不变。
3. **不同人（different）**：只改状态与 resolution，两个身份都保留。
4. **暂缓（defer）**：状态 `deferred`，保留证据，列表可单独筛选。
5. **并发**：只有 `status='open'` 可处理，重复提交返回 409 `conflict_already_resolved`。
6. **审计**：每次操作写 `identity_conflict_actions`（操作者、动作、决策、备注、合并统计），只追加不修改。

### 数据库变更

`a4d8e1f63c09`：新增 `identity_conflict_actions` 表 + 4 个索引；`upgrade → downgrade → upgrade` 在 SQLite 已验证。

### 新增测试（`backend/tests/test_sm011_identity_center.py`）

- 列表筛选/分页/计数；
- 详情包含双方证据、来源、历史；
- 合并同一人：实例迁移、快照数量不变、审计写入；
- 确认不同人：身份数量不变；
- 暂缓：状态 deferred 且可筛选；
- 并发确认：第二次 409；
- 跨用户/跨存档：列表不可见、详情 404、处理 404；
- 审计历史可读取。

### 前端

`/identity` 页面：待处理/已解决/暂缓计数、冲突列表（分页）、双方对比（姓名、生日、国籍、实例、快照、来源）、
系统建议、备注 + 三个确认操作、操作历史。加载/错误/空状态复用现有组件。

前端 `npm run build`（vue-tsc + vite）通过；**未在真实浏览器中点验交互**（无 E2E 环境）。

### 未解决问题

- 合并只处理"当前存档内实例"；跨存档合并属于 SM-014（Global Player Identity）范围，本轮不做。
- 前端未加 e2e 测试，仅有类型检查与构建验证。
- 冲突列表默认只显示 `open`，`deferred` 需要切换筛选。

## 四、SM-012 FM27.1 Reader 稳定性与字段质量

### 目标

让 Reader 的字段可信度、合同日期异常、连续扫描稳定性和执行布局可诊断、可复现。

### 修改文件

- `live-reader/ScoutMind.FMReader/Engine/FieldMetadata.cs`（新增）
- `live-reader/ScoutMind.FMReader/Probes/ContractDateDiagnostics.cs`（新增）
- `live-reader/ScoutMind.FMReader/Probes/ObjectProbes.cs`（合同日期分类统计）
- `live-reader/ScoutMind.FMReader/Engine/FMSuperScoutMemoryEngine.cs`（取消不再抛异常）
- `live-reader/tools/ScoutMind.FMReader.Diag/Program.cs`（`fields` 命令）
- `live-reader/tests/ScoutMind.FMReader.Tests/StabilityTests.cs`（新增）
- `live-reader/tests/ScoutMind.FMReader.Tests/Program.cs`

### 核心实现

1. **字段元数据**（`fields` 命令）：50 个字段，逐字段输出偏移、数据类型、可信度、证据来源、适用版本、验证方式；
   统计：Verified 11 / Candidate 7 / Pending 32。Candidate（例如 `PLAO_HEIGHT`）**不会**因为整体允许扫描而升级。
2. **合同日期诊断**：`ContractDateDiagnostics` 把原始 u32 分成未设置(0) / 全 1 哨兵 / 序日非法 / 年份越界 / 可解码，
   报告里给出各类计数与可解码比例，替换原来只有"29%"的笼统比例。
   真实样本 17 个可解析合同中 12 个异常的现象现在可以定位到具体类别（需要下次真实扫描生成报告）。
3. **取消语义**：扫描前已取消返回可读失败原因（`扫描已取消。`），不再抛 `TaskCanceledException`。
4. **连续扫描稳定性**：同一 dump 连续 10 次扫描，报文逐字节一致；无合同球员不中断；读取失败/取消都返回明确原因。

### 数据库变更

无。

### 新增测试（`StabilityTests`，7 项）

- 字段元数据完整性与 Verified/Candidate 计数；
- Candidate 不被升级；
- 合同日期分类：未设置 vs 哨兵、序日非法、年份越界、可解码；
- 连续 10 次扫描结果一致；
- 无合同球员不中断；
- 进程退出（阅读失败）返回失败而非空数据；
- 取消立即失败。

### 测试结果

FMReader 测试：**104 / 104** 通过；Reader 集成测试 46 / 46。

### 真实环境验收 — PASS（10 次连续扫描）

执行时 Football Manager 2027 未运行（`fm.exe` 不存在），因此：

- 未执行真实的 10 次连续扫描；
- 未生成带合同日期分类的真实诊断报告；
- 未重新核对 Build 26620374 的字段可信度。

历史真实验收记录保留在 `docs/acceptance/VERIFY-2026-11-20-PHASE1.md`（50,365 球员、两次扫描一致）。

**口径区分**：
- 历史真实验收（2026-11-20 早间）：PASS，记录在 `VERIFY-2026-11-20-PHASE1.md`；
- 本轮单元测试：104 项 FMReader 测试，PASS；
- 本轮真实环境验收（2026-11-20 晚间 10 次扫描）：PASS，记录在 `VERIFY-2026-11-20-SM012-READER.md`；
- 合同到期日根因：PARTIAL（已定位到非标准合同对象，未修复）；
- 扫描耗时/内存峰值指标：NOT_RUN。

### 未解决问题

- 合同日期异常的具体根因（哪个偏移/哪类对象）需要下次真实扫描报告中的 `expiry_diagnostics` 才能定位；
  目前只提供分类工具与隔离策略（不阻塞扫描、不提升字段可信度）。
- 扫描耗时/内存峰值指标尚未写入 `ScanMeta`（本轮只做了字段与稳定性；指标属于 SM-012 的"可观测性"部分，未完成）。

## 五、总回归（本轮实际执行）

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| Backend | `cd backend; .\.venv\Scripts\python.exe -m pytest` | **232 passed** |
| FMReader | `dotnet run -c Release`（live-reader/tests/ScoutMind.FMReader.Tests） | **104 / 104** |
| Reader | `dotnet run -c Release`（live-reader/tests/ScoutMind.Reader.Tests） | **46 / 46** |
| Frontend | `cd frontend; npm run build` | 成功 |
| 迁移 | `a4d8e1f63c09`、`b6e2f4a70d15` upgrade/downgrade/upgrade | 通过 |

## 五之三、第三阶段（SM-017 / SM-018 / SM-019 / SM-020）

### SM-017 转会决策模拟器 — PASS

- `POST /transfers/simulate`：输入球员/位置/报价/工资/年限/预算/出场时间/交易类型；
  输出成本、合理报价区间（P25/中位/P75 或估值区间）、阵容前后对比、乐观/基准/悲观三情景、
  预算判断、风险清单、3 个替代方案与推荐结论。
- 确定性：相同输入两次结果完全一致（测试断言 JSON 相等）；不引入随机数或训练模型。
- 缺失数据（CA/PA/身价/工资）列入 `data_gaps` 与风险，不填 0；区间给不出来时明确 unknown。
- 测试：确定性、预算超支、缺少球员 404。

### SM-018 AI Sporting Director 2.0 — PARTIAL

- 工具白名单从 9 个扩到 **14 个**：新增 `simulate_transfer`、`player_forecast`、
  `club_transfer_intelligence`、`transfer_roi`、`recruitment_recommend`、`career_timeline`；
  全部只调用确定性分析函数，`save_id` 仍由服务端注入并被禁止出现在参数里。
- 工具调用上限、Schema 校验、降级、`llm_fallback` 原因、数字校验逻辑沿用 SM-009。
- 测试：白名单包含新工具、`save_id` 注入被拒、假客户端驱动模拟器、工具执行失败降级。
- **未接真实 LLM**（无 API Key）：真实模型规划质量未验证，故 PARTIAL。

### SM-019 球员成长预测 — PASS

- `GET /players/{id}/forecast`：最小二乘成长速率 + 年龄曲线回退；预测按 PA 封顶；
  区间由分区间速率标准差决定；快照 <3 时置信度 low 且不给 3 年预测。
- `GET /development/forecast-backtest`：滚动回测（前 N-1 个快照预测最后一点），输出 MAE/RMSE/区间覆盖率。
- 测试：观测速率、PA 封顶、单快照低置信、回测指标。
- **真实存档回测 NOT_RUN**：真实存档中没有任何球员拥有 ≥2 个带 CA 的历史快照（重复扫描被去重），
  回测需要时间序列，等累积多轮扫描后再跑；不用合成数据冒充。

### SM-020 自动引援推荐 — PASS

- `POST /recruitment/recommend`：位置/年龄/预算/工资/联赛/国籍过滤，`prefer=ready|potential|balanced`，
  用户可覆盖六维权重；缺失维度不参与加权并计入 `missing_dimensions`；分页；每条带分维解释与风险。
- 测试：超预算过滤、潜力权重改变排序、未知权重 422。

## 六、下一阶段依赖（SM-013 起）

1. **历史转会数据来源**必须先做技术调查：当前 FMSuperScout 导出没有历史交易数组，
   `transfer_history.available=false`；不得用 `transferDate` 推断历史成交。
2. 需要真实 FM27 环境补跑 SM-012 的 10 次连续扫描与合同日期诊断，才能把该任务从 PARTIAL 提升。
3. SM-011 的合并逻辑只覆盖存档内身份；跨存档全局身份属于 SM-014。

## 七、状态汇总

> 本报告是 V3（SM-010～SM-020）的历史记录；V3.1 第一阶段（SM-021～SM-024）见
> `docs/SCOUTMIND-V3.1-IMPLEMENTATION-REPORT.md`。

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-010 | PASS | 实现 + 安全测试通过 |
| SM-011 | PASS（前端仅构建验证） | 后端 API/权限/审计 + 前端页面 |
| SM-012 | PASS（合同根因与指标另列） | 10 次真实扫描 PASS；合同异常 PARTIAL；扫描指标 NOT_RUN |
| SM-013～SM-020 | NOT_RUN | 本轮未授权 |
