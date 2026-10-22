# MCP_INTEGRATION.md

本项目实际使用的麦当劳 MCP Server、调用工具、调用流程与业务价值。

---

## 1. MCP Server

| 项 | 值 |
| --- | --- |
| 接入地址 | `https://mcp.mcd.cn`（Streamable HTTP，**根路径**） |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCP Token>` |
| Token 申请 | https://open.mcd.cn/mcp → 登录 → 控制台 → 激活 |
| 限流 | 每个 Token 每分钟最多 600 次请求，超出返回 `429` |
| 错误码 | `401` Token 无效/过期；`429` 触发限流 |
| 接入示例 | `mcp-config.example.json`（仅环境变量占位符，不含真实 Token） |

### 一个容易踩的坑

官方文档示例里写过 `https://mcp.mcd.cn/mcp`。实测该路径在当前服务端返回 **404 Route Not Found**，正确入口是根路径 `https://mcp.mcd.cn`。

`scripts/fetch_raw.py` 对此做了兼容：先试根路径，失败再回退 `/mcp`，并在输出里打印实际连上的地址。客户端若已接入 MCP（如 Claude Code、Cursor、WorkBuddy），按 `mcp-config.example.json` 配根路径即可。

### 协议交互

标准 MCP Streamable HTTP 握手，`scripts/fetch_raw.py` 里完整实现了这一段：

1. `POST /` → `initialize`，带 `protocolVersion: 2025-06-18`
2. 响应头取 `Mcp-Session-Id`，后续请求都要带上
3. `POST /` → `notifications/initialized`（通知，无返回体）
4. `POST /` → `tools/list` 拿工具清单，`tools/call` 调用工具

服务端目前提供 **35 个工具**，本项目只用了其中 8 个**只读**工具。

---

## 2. 使用的工具

| 工具 | 用途 | 体检里的作用 |
| --- | --- | --- |
| `now-time-info` | 服务器当前时间 | 报告基准时间；券到期天数按服务器日期算，避免客户端时区误差 |
| `order-list` | 历史订单（非商城） | 营养/钱包/习惯三个维度的主数据源 |
| `list-nutrition-foods` | 常见餐品营养成分表 | 热量、蛋白质、脂肪、碳水、钠、钙的计算依据 |
| `query-my-account` | 积分账户 | 权益把控：可用/累计/已用/已过期/本月将过期 |
| `query-my-coupons` | 我的优惠券 | 权益把控：临期券提醒（券的到期时间从返回文本解析） |
| `mall-order-list` | 麦麦商城订单 | 积分兑换历史，衡量积分使用效率 |
| `query-lottery-info` | 积分抽奖活动信息 | 只读展示抽奖消耗与奖品，不触发抽奖 |
| `campaign-calendar` | 当月营销活动日历 | 给「今天换点什么」的尝新建议 |

**未使用的消耗型工具**：`auto-bind-coupons`（一键领券）、`draw-lottery`（积分抽奖）、`mall-create-order`（积分兑换）、`create-order` / `cancel-order`（下单/取消）。体检是只读行为，这些一律不碰。

---

## 3. 调用流程

```
                    ┌──────────────────────┐
                    │  now-time-info       │──→ 报告基准时间 / 到期天数基准
                    └──────────┬───────────┘
                               │
  ┌────────────────┐   ┌──────┴───────┐   ┌──────────────────┐
  │ order-list     │   │ list-        │   │ query-my-account │
  │ 历史订单       │   │ nutrition-   │   │ 积分账户         │
  │ 9 单 / 30 个餐品│   │ foods        │   │ 6 项积分指标     │
  └───────┬────────┘   │ 158 条营养   │   └────────┬─────────┘
          │            └──────┬───────┘            │
          └───────┬────────────┘                    │
                  │ 套餐拆解 + 分级匹配               │
                  ▼                                  │
        ┌──────────────────┐                        │
        │  营养匹配引擎     │  精确/近似/估算/未覆盖    │
        └────────┬─────────┘                        │
                 ▼                                  ▼
  ┌───────────────┐   ┌──────────────┐   ┌──────────────────┐
  │ query-my-     │   │ mall-order-  │   │ query-lottery-   │
  │ coupons 券    │   │ list 商城订单 │   │ info 抽奖信息     │
  └───────┬───────┘   └──────┬───────┘   └────────┬─────────┘
          └──────────┬────────┴────────────────────┘
                     ▼
        ┌────────────────────────────┐
        │  health_report.py 体检引擎  │
        │  统计 → 四维评分 → 建议生成   │
        └─────────────┬──────────────┘
                      ▼
     report.json  │  report.md  │  report.html（可分享卡片）
```

### 单次体检的完整调用序列

```bash
export MCD_TOKEN=<你的 Token>
python3 scripts/fetch_raw.py --out raw          # 8 个只读工具
python3 scripts/health_report.py --raw-dir raw --out out --name "你的昵称"
```

`fetch_raw.py` 会自动完成 MCP 握手、逐个调用工具、把返回文本落盘为 `raw/<工具名>.txt`。若客户端已接入 `mcd-mcp`，也可以由 agent 直接调用这 8 个工具后按同样的文件名落盘，两条路径等价。

---

## 4. 关键数据处理

### 4.1 套餐必须拆开算

`order-list` 返回的 `orderProductList[].comboItemList` 才是套餐的真实组成。例如「人气经典随心配」在订单里是一个商品，但它拆出来是 `双层吉士汉堡 ×1` + `可乐大杯 ×1`。营养表里**只有单品、没有套餐**，所以不做拆解就完全算不出热量。

实测一份 9 单的历史记录，拆开后共 30 个餐品条目。

### 4.2 营养表是紧凑自定义格式

`list-nutrition-foods` 返回的 `data` 字段不是 JSON，而是：

```
[158]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  可乐大杯,null,936,224,0,0,55,0,15
```

解析时要按「名称 + 末尾 7 个数值」切，不能假设每行固定 9 列（`nutritionDescription` 为 `null` 时列数会少一列）。

### 4.3 分级匹配，公开覆盖率

营养表 158 条，而用户点的是当季新品（`泰式炭烤风味猪猪堡`、`高达吉士双牛堡`、`美芝芝拉丝鸡肉堡`…），名称对不上是常态。引擎按四级处理，并把结果写进报告：

| 级别 | 判定方式 | 处理 |
| --- | --- | --- |
| 精确 | 名称直接命中营养表 | 精确值 |
| 近似 | 包含关系且覆盖过半（如 `板烧鸡腿堡` ↔ `双层吉士汉堡` 的同族项） | 标注「按同类单品估算」 |
| 估算 | 按品类（汉堡/炸物/小食/饮料/甜品/早餐）中位数兜底 | 标注 `≈` |
| 未覆盖 | 上述都不成立 | 不参与热量推断，列出餐品名 |

酱料类（`韩式甜辣酱`、`北美招牌牧场酱` 等）按 0 热量计入。

实测：30 个餐品条目中精确命中 21 个、品类估算 9 个、未覆盖 0 个，覆盖率 70%。**这个覆盖率会原样出现在报告底部**，估算值在复购榜里带 `≈` 标记。

### 4.4 券的到期时间藏在 markdown 里

`query-my-coupons` 返回的是 markdown 而不是 JSON，格式形如：

```markdown
## 11.9元麦辣鸡腿堡
- **优惠**: ¥11.9 (用券价格)
- **有效期**: 2026-10-19 10:30-2026-10-23 23:59 周一、二、三、四、五 10:30-23:59
```

用正则 `(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*[-–—~至]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})` 取出起止时间，再以 `now-time-info` 的服务器日期算剩余天数，3 天内到期的券会被列为「速办」。

### 4.5 积分的四个坑

`query-my-account` 的字段名有迷惑性，容易算错：

- `availablePoint` 可用积分
- `accumulativePoint` **累计获得**（不是余额）
- `usedPoint` 已使用
- `expiredPoint` **已过期**——这是纯亏损，用 `expired / accumulative` 衡量
- `currentMouthExpirePoint` 本月即将过期，是「还没亏但快亏了」的积分

体检的「权益把控」维度同时看这五个数，避免只看余额而漏掉过期损失。

---

## 5. 业务价值

| 场景 | MCP 提供的原始能力 | 本项目变成的决策 |
| --- | --- | --- |
| 券快过期没人提醒 | `query-my-coupons` 返回券和到期时间 | 报告顶部「速办」项，直接告诉你哪张券剩几天、值多少钱 |
| 积分悄悄过期 | `query-my-account` 的 `expiredPoint` / `currentMouthExpirePoint` | 过期损失量化 + 兑换优先级建议 |
| 不知道吃麦当劳健不健康 | `order-list` + `list-nutrition-foods` | 拆套餐、按订单汇总，算出单餐热量与钠摄入，对照膳食指南给出可执行替换（大杯可乐 → 无糖中杯） |
| 消费全靠感觉 | `order-list` 的金额、门店、时间 | 客单价、月均消费、门店集中度、深夜档占比 |
| 总是重复点老三样 | `campaign-calendar` | 结合当月活动给出尝新建议 |

一句话：**MCP 提供的是「能查到」，本项目提供的是「看完知道该做什么」。**

---

## 6. 可复现性

- 所有数字都来自 MCP 实时返回，脚本不做任何数值假设。
- 评分权重、参考值、匹配规则全部写在代码常量与 `references/report-spec.md` 里，可审计。
- `raw/` 里保存的是未经修改的原始返回，任何人都能重跑 `health_report.py` 复现同一份报告。
