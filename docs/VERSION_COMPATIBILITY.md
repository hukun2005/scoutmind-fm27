# 版本兼容性策略（VERSION_COMPATIBILITY）

本文档定义 ScoutMind 读取器的**版本闸门**：什么情况下允许读取 FM27，什么情况下必须拒绝。
它与 `docs/LIVE_READER.md` 配套阅读；接口字段见 `docs/API.md` 的 `GET /compatibility`。

---

## 1. 为什么需要版本闸门

FM27 的 `game_plugin.dll` 每次游戏更新都会变化。内存布局一旦变化，旧偏移量读出来的就是
**错误的数据**——比读不到更糟，因为错误数据会静默污染后续所有分析。

因此本项目的规则是：**不匹配就拒绝，绝不猜测**。

- 不做"最接近版本"匹配。
- 不做"旧版本偏移量兜底"。
- 不使用模糊版本比较（`27.*` 之类），只做精确字符串比对。

---

## 2. 兼容清单 `compatibility.json`

仓库源文件：`config/compatibility.json`，构建时复制到读取器输出目录。
可用环境变量 `SCOUTMIND_COMPATIBILITY_FILE` 指向其他清单。

```json
{
  "schemaVersion": 1,
  "entries": [
    {
      "appId": "4530370",
      "buildId": "26577676",
      "pluginProductVersion": "27.0.1+2503222",
      "status": "candidate",
      "notes": "未验证的 Windows 预览候选：……",
      "verifiedAt": null
    }
  ]
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schemaVersion` | 整数 | 当前只接受 `1`；其他值直接报错并拒绝读取 |
| `entries[].appId` | 字符串 | Steam AppId，FM27 为 `4530370` |
| `entries[].buildId` | 字符串 | `appmanifest_4530370.acf` 中的 `buildid` |
| `entries[].pluginProductVersion` | 字符串 | `game_plugin.dll` 的产品版本（含 `+` 构建后缀） |
| `entries[].status` | 枚举 | `candidate` / `verified` / `rejected` |
| `entries[].notes` | 字符串 | 中文说明，会出现在拒绝原因里 |
| `entries[].verifiedAt` | 时间或 `null` | 本机完成验证的 UTC 时间 |

---

## 3. 匹配规则

判定输入是本机**实测**的三个值：

1. `appId`：来自 Steam 清单（或内置常量 `4530370`）
2. `buildId`：来自 `appmanifest_*.acf` 的 `buildid`
3. `pluginProductVersion`：来自 `game_plugin.dll` 的 `ProductVersion`

匹配顺序：

| 步骤 | 条件 | 结果 |
| --- | --- | --- |
| 1 | 缺少 `appId` | `Unknown`（无法判定） |
| 2 | 清单中没有该 `appId` 的条目 | `Unsupported` |
| 3 | 缺少 `buildId` | `Unknown` |
| 4 | 没有该 `buildId` 的条目 | `Unsupported`（列出清单已知构建） |
| 5 | 缺少插件产品版本 | `Unknown` |
| 6 | `buildId` 命中但 `pluginProductVersion` 不匹配 | `Unsupported`（同时记录实际值与清单值） |
| 7 | 三者全命中且 `status=verified` | `Verified` → `Compatible` |
| 8 | 三者全命中且 `status=candidate` | `Candidate` → `Unknown`，原因固定为"候选兼容项，需本机 probe 验证" |
| 9 | 三者全命中且 `status=rejected` | `Rejected` → `Unsupported` |

比较细节：

- `appId`、`buildId`：去除首尾空白后**不区分大小写**比较（都是数字串）。
- `pluginProductVersion`：去除首尾空白后**精确**比较（区分大小写），不解析为 `System.Version`。
- 空清单（`entries: []`）等价于"什么都不知道"：所有构建都会被判 `Unsupported`。

---

## 4. 状态到行为的映射

| 兼容性状态 | 读取器状态 | 允许 probe | 允许 scan |
| --- | --- | --- | --- |
| `verified` | `Compatible` | ✅ | 需先 probe 通过 |
| `candidate` | `Unknown` | ❌ | ❌ |
| `rejected` | `Unsupported` | ❌ | ❌ |
| （无匹配） | `Unsupported` | ❌ | ❌ |

退出码：`Unknown` / `Unsupported` → 3；`Compatible` → 0。

**`candidate` 永远不会自动升级为兼容**。它只是"待验证的线索"，需要本机 probe 通过后由人工改为
`verified`。

---

## 5. 如何把一个候选条目升级为已验证

1. 在**安装该构建**的机器上，用正确的 `scanner.json` 执行：
   ```powershell
   ScoutMind.LiveReader.exe status          # 确认 build 与插件版本
   ScoutMind.LiveReader.exe probe           # 扫描器自检
   ScoutMind.LiveReader.exe scan --output .\scans
   ```
2. 确认 `scan` 退出码为 0，且落盘的信封里是**真实数据**（球员数量、字段合理性）。
3. 修改 `config/compatibility.json`：
   - `status` 改为 `"verified"`
   - `verifiedAt` 填 UTC 时间，例如 `"2026-11-20T09:30:00Z"`
   - `notes` 记录验证环境（Windows 版本、游戏构建、扫描器版本）
4. 重新构建/发布，使新的 `compatibility.json` 进入输出目录。
5. 把实际观测到的三个值原样写入，不要"顺手"写成别的版本号。

> 在此之前，任何未知构建都必须被拒绝——这是该项目最重要的安全属性。

---

## 6. 本机现状（开发机实测）

| 项目 | 值 |
| --- | --- |
| 清单条目 | `buildId=26577676`，`plugin=27.0.1+2503222`，`status=candidate` |
| 本机 `buildid` | `26620374` |
| 本机插件产品版本 | `27.1.0+2505117` |
| 判定 | `Unsupported`：未收录的构建 26620374 |
| 退出码 | 3 |

也就是说：**本机没有通过版本闸门，也没有完成过任何一次真实扫描**。
候选条目与新构建不一致，读取器按设计拒绝读取。

---

## 7. 常见问题

**问：能不能加一个"我确定要读"的开关强行跳过闸门？**
不能。跳过闸门等于允许读取未知布局的内存，会产出看似真实但实际错误的球员数据。

**问：为什么插件版本也要匹配？**
因为 `game_plugin.dll` 是实际提供读取能力的模块。同一个游戏构建可能加载不同插件版本
（例如用户替换过文件），此时内存布局与偏移量都可能不同。

**问：游戏更新后读取器会怎样？**
`buildid` 变化 → 没有对应条目 → `Unsupported`，退出码 3，附带清单已知构建列表。
此时需要重新验证并新增条目。

**问：清单损坏会怎样？**
`compatibility.json` 缺失、非法 JSON 或 `schemaVersion` 不受支持时，读取器进入 `Unknown` 并拒绝读取
（`compatibility list` 返回 3 并打印原因）。它不会退回"默认兼容"。

---

## 8. 本机观测记录（2026-11-18）

开发机已安装 FM27，读取器 `status` 的实测结果：

| 项 | 实测值 |
| --- | --- |
| Steam 库 | `D:\steam` |
| App Manifest | `steamapps\appmanifest_4530370.acf` |
| Steam Build ID | `26620374` |
| 安装目录 | `D:\steam\steamapps\common\Football Manager 27` |
| `game_plugin.dll` 实际位置 | `fm_Data\Plugins\x86_64\game_plugin.dll` |
| 插件 ProductVersion | `27.1.0+2505117` |

结论：本机构建 **不在** 已知候选组合（`26577676` / `27.0.1+2503222`）中，读取器返回 `Unsupported`
（exit code 3）并拒绝扫描，这是正确行为。上述实测组合已作为第二条 `candidate` 写入 `config/compatibility.json`，
但**没有**经过 probe 验证，因此状态保持 `candidate`，读取器仍然拒绝读取。

要真正开始读取，必须：

1. 准备一个经过审查的外部只读扫描器，并在 `scanner.json` 中配置其路径与参数；
2. 用该扫描器支持的确切构建核对版本；
3. 在确认兼容后，把对应条目改为 `verified` 并填写 `verifiedAt`，再执行 `probe` 与 `scan`。

在完成上述步骤之前，任何“成功读取 FM27”的说法都不成立，`samples/demo` 里的数据也只是合成演示数据。
