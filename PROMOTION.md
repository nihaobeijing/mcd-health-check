# 推广素材（PROMOTION）

本项目在本次赛事中**只按 GitHub Star 数排名**（详见活动规则「评审与排名」）。当前第 100 名约 33 Star，第 1 名约 890 Star。
所以下面的文案不是附赠品，是直接影响排名的手段。

---

## 1. 一句话介绍

> 用麦当劳官方 MCP 给你的真实消费数据做个体检：算麦门健康分、拆套餐算热量、抓临期券和过期积分，输出一张能直接发朋友圈的报告卡。

---

## 2. 社交平台文案

### 微博 / 小红书（短、带图）

```
我用麦当劳的官方 MCP 给自己的消费记录做了个体检 🩺

麦门健康分 74.1（B）
最扎心的一条：单餐钠摄入占到了每日上限的 51%，
建议把大杯可乐换成无糖中杯。

它做了一件我自己从来没做过的事：
把套餐拆开算热量、把临期券和过期积分揪出来。
最后给我一张这样的报告卡 👇

（附：demo/report_demo.html 截图）

开源在 GitHub：github.com/nihaobeijing/mcd-health-check
不用 API Key 也能跑：python3 scripts/health_report.py --demo
#麦当劳程序员创意开发大赛 #MCP #AgentSkills
```

### 掘金 / 知乎（长、偏技术）

```
【麦当劳 MCP 实战】把 158 条营养表和你的真实订单对起来，算出你一餐到底吃了多少钠

背景
麦当劳 MCP 提供了 35 个工具，但原始数据离「行动建议」很远。

三个具体的坑：
1. 营养表只有单品没有套餐 —— 必须把 order-list 里的 comboItemList 拆开再累加，否则完全算不出热量
2. 当季新品（如「泰式炭烤风味猪猪堡」）在 158 条营养表里对不上 —— 做了四级匹配：精确 / 近似 / 品类中位数 / 未覆盖，并把覆盖率如实写进报告
3. 券的到期时间藏在 markdown 文本里 —— 正则出起止时间，按 MCP 服务器时间算剩余天数

实现要点
- fetch_raw.py 完整实现 MCP Streamable HTTP 握手（initialize → Mcp-Session-Id → notifications/initialized → tools/call），纯标准库
- health_report.py 只吃落盘的原始返回，任何人都能复现同一份报告
- 全程只调用 8 个只读工具，领券/抽奖/下单一律不碰

GitHub：github.com/nihaobeijing/mcd-health-check
```

### GitHub Issue / PR 末尾附言

```
如果这个体检报告帮你省下了一次过期积分或一张临期券，记得点个 ⭐ Star
——本次赛事的排名完全按 Star 数计算。
```

---

## 3. 冷启动清单（按性价比排序）

| 动作 | 说明 | 预估 Star |
| --- | --- | --- |
| 用自己的真实数据生成报告卡，发微博/小红书 | 附上卡片截图 + 仓库链接，这是最自然的一次曝光 | 5–20 |
| 发掘金/知乎技术贴 | 拆套餐、分级匹配这些点很适合技术社区 | 10–30 |
| 在麦当劳 MCP 相关的 issue / PR 下留言介绍 | 官方仓库的 issue 区有大量参赛者和观望者 | 5–15 |
| 微信群 / 朋友圈 / 同学群 | 目标用户就是麦门常客，转化率最高 | 5–15 |
| 给自己的 PR / 仓库互相 Star | 有效但要克制 | 少量 |

**卡片最好自己生成**：真实数据的报告卡比官方示例更有说服力。

```bash
export MCD_TOKEN=<你的 Token>
python3 scripts/fetch_raw.py --out raw
python3 scripts/health_report.py --raw-dir raw --out out --name "你的昵称"
# out/report.html 用浏览器打开就是卡片，截图分享
```

---

## 4. 想拿 WorkBuddy 专项 3000 积分？

活动规则里，排行榜前 100 名提交 `workbuddy.md` 即可获得 WorkBuddy 3000 积分，前 3 名额外 10240 积分。

本项目是在 Command Code 中开发的，没有 WorkBuddy 对话记录，所以仓库里**没有** `workbuddy.md`——不会伪造一个。若要参加该项：

1. 在 WorkBuddy 里安装同样的 MCP（参考官方文档「WorkBuddy 开发指南」）
2. 把本仓库的 Skill 装进 WorkBuddy
3. 在 WorkBuddy 里实际跑一遍体检
4. 从 WorkBuddy 导出对话上下文，保存为仓库根目录的 `workbuddy.md`

---

## 5. 别做的事

- 不要用机器人批量 Star 或买 Star —— 活动规则明确要求「真实使用 MCP 能力」，人工审核会看仓库内容
- 不要在宣传文案里写「官方」或暗示麦当劳背书
- 分享自己的报告卡前留意：卡片里含真实订单与积分数据，公开前确认可接受
