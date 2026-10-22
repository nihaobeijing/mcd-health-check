# 麦门健康体检官 · mcd-health-check

> 把你真实的麦当劳消费数据，变成一份体检报告。

一个基于**麦当劳官方 MCP Server** 的 Agent Skill。它不生成建议清单，而是拿你真实的订单、积分和优惠券，算出一个可复现的**麦门健康分**，并给出「该做什么」的行动项和一张可分享的报告卡。

```
麦门健康分 68.1（C）
最短板在「权益把控」（33.5 分）——你的账户里有这张券还没用，还剩 1 天。
```

---

## 为什么做这个

麦当劳 MCP 提供了 35 个工具，能查订单、查营养、查积分、查券。但原始数据是「能查到」，不是「看完知道该做什么」：

- 券的到期时间藏在 markdown 文本里，没人提醒
- 积分过期了（`expiredPoint`）大多数人不看
- 营养表 158 条全是单品，套餐得自己拆才知道一餐多少热量
- 单餐钠摄入能占到每日上限的 74%，但没人算过

这个 Skill 把这四件事补上，并且**每一分都可追溯到 MCP 返回的原始数据**。

## 亮点

| | |
| --- | --- |
| **套餐拆解** | `order-list` 的 `comboItemList` 拆开再算营养，营养表里只有单品不做拆解等于算不出来 |
| **分级匹配 + 公开覆盖率** | 精确 / 近似 / 品类估算 / 未覆盖四级，报告底部如实给出覆盖率，估算值标 `≈` |
| **券到期预警** | 从 markdown 返回里正则出券的到期时间，按 MCP 服务器时间算剩余天数 |
| **积分体检** | 同时看可用、累计、已用、**已过期**、本月将过期五个口径，不只看余额 |
| **只读安全** | 全程只调用 8 个只读工具，领券/抽奖/下单一律不碰 |
| **零依赖** | 纯 Python 标准库，完整实现 MCP Streamable HTTP 握手 |

## 快速开始

### 1. 拿 Token

到 [open.mcd.cn/mcp](https://open.mcd.cn/mcp) 用手机号登录 → 控制台 → 激活 → 复制 MCP Token。

### 2. 跑起来

```bash
git clone https://github.com/<你的用户名>/mcd-health-check.git
cd mcd-health-check

export MCD_TOKEN=你的Token

# 拉取 MCP 数据（8 个只读工具）
python3 scripts/fetch_raw.py --out raw

# 生成体检报告
python3 scripts/health_report.py --raw-dir raw --out out --name "你的昵称"
```

产出三个文件：

| 文件 | 说明 |
| --- | --- |
| `out/report.html` | 自包含的可分享报告卡（内联 CSS/SVG，单文件，可直接发朋友圈） |
| `out/report.md` | 文字版报告 |
| `out/report.json` | 结构化指标，便于二次分析 |

Python 3.8+，**不需要 pip install 任何东西**。

### 3. 作为 Skill 使用

本目录符合 [Agent Skills](https://agentskills.io/specification) 规范，复制到技能目录即可被识别：

```bash
cp -r mcd-health-check ~/.commandcode/skills/        # Command Code
cp -r mcd-health-check ~/.claude/skills/             # Claude Code
```

之后直接说「来份麦门体检」「我的麦当劳消费分析」就能触发。

如果你的 MCP 客户端已经接入麦当劳 MCP，也可以让 agent 直接调工具后落盘，详见 `MCP_INTEGRATION.md`。

## 使用示例

**输入**

> 来份我的麦门体检

**输出（节选）**

```
麦门健康分 68.1（C）｜ 最短板：权益把控 33.5

🔴 速办  11.9元麦辣鸡腿堡（还剩 1 天）
         你的账户里有这张券还没用，还剩 1 天。去常去的门店点单时优先用掉。
⚠️ 注意  累计 1860.2 积分里已有 1183.4 过期
         过期比例 64%。积分不像现金，不花就会清零。
⚠️ 注意  单餐平均钠摄入 1478 mg
         每日钠建议上限 2000 mg，单餐占到 74%。把大杯可乐换成无糖中杯，
         单餐能少几百毫克钠。

数据可信度：精确 21 ｜ 近似 0 ｜ 品类估算 9 ｜ 未覆盖 0，覆盖率 70%
```

## 报告长什么样

`report.html` 是一张 472px 宽的卡片：SVG 环形健康分、四维迷你环、堆叠供能比条、复购榜、虚线券票、行动建议卡片、覆盖率说明。全部内联，无外部依赖，存下来就能发。

## 项目结构

```
mcd-health-check/
├── SKILL.md                      # Skill 指令（Agent Skills 规范）
├── README.md
├── MCP_INTEGRATION.md            # 使用的 MCP Server / Tool / 调用流程 / 业务价值
├── CONTEST_DECLARATION.md        # 官方参赛声明（原样引用）
├── mcp-config.example.json       # 脱敏 MCP 配置示例
├── scripts/
│   ├── fetch_raw.py              # MCP 取数器（完整实现 Streamable HTTP 握手）
│   └── health_report.py          # 体检引擎（匹配 → 统计 → 评分 → 渲染）
├── assets/
│   └── report_card.html          # 报告卡模板（string.Template 占位符）
├── references/
│   └── report-spec.md            # 评分口径与参考值来源
└── raw/                          # MCP 原始返回（.gitignore）
```

## 数据与隐私

- 所有数据来自你自己的 MCP Token，只在本机与你配置的 MCP Server 之间流动。
- 仓库里不含任何 Token、密钥或真实账号数据；`mcp-config.example.json` 只用 `${MCD_TOKEN}` 占位符。
- `raw/` 目录包含你的真实订单与积分数据，已在 `.gitignore` 中排除，**不要**提交。
- 报告是个人消费数据分析，不构成医疗或营养建议。

## 目标用户

- 想少浪费优惠券和积分的麦门常客
- 在控制饮食热量与钠摄入、但又不想放弃麦当劳的人
- 喜欢把自己的数据做成报告卡分享的人

## 免责声明

本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品。餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。

## License

MIT
