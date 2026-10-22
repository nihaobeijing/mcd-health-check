---
name: mcd-health-check
description: 麦门健康体检官。基于麦当劳官方 MCP Server 的真实数据（历史订单、餐品营养表、积分账户、优惠券、积分商城订单、活动日历），生成一份麦门健康体检报告：麦门健康总分、营养均衡/钱包健康/权益把控/习惯结构四维评分、单餐热量与钠摄入分析、优惠券与积分到期提醒，以及一张可分享的 HTML 报告卡。当用户说「麦门体检」「麦当劳健康报告」「我的麦当劳消费分析」「我吃麦当劳健康吗」「麦门健康分」「看看我的券要过期了吗」时使用。
license: MIT
metadata:
  version: "1.0.0"
  author: mcd-health-check
---

# 麦门健康体检官

把用户的真实麦当劳消费数据，变成一份「体检报告」。

## 何时使用

用户想了解自己的麦当劳消费习惯、营养摄入、积分与优惠券状况时。典型说法：麦门体检、麦当劳健康报告、我的消费分析、我吃麦当劳健康吗、我的券快过期了吗。

## 前置条件

- 麦当劳 MCP Token（申请地址 https://open.mcd.cn/mcp，登录后控制台 → 激活）。
- Python 3.8+，仅用标准库，无需 pip 安装。

## 执行步骤

### 第 1 步：确认 MCP Server 可达

```bash
python3 scripts/fetch_raw.py --list-tools
```

若提示找不到 Token，让用户设置环境变量 `MCD_TOKEN`（或写入 `~/.mcd_mcp_token`），**不要**让用户把 Token 写进代码或提交到仓库。

### 第 2 步：拉取数据

```bash
python3 scripts/fetch_raw.py --out raw
```

这一步会调用 8 个只读工具，把原始返回原样存到 `raw/<工具名>.txt`：

`now-time-info`、`order-list`、`list-nutrition-foods`、`query-my-account`、`query-my-coupons`、`mall-order-list`、`query-lottery-info`、`campaign-calendar`

如果当前 MCP Client 已经接入 `mcd-mcp`（见 `mcp-config.example.json`），也可以由 agent 直接调用这些工具，再把返回文本按同样的文件名写入 `raw/`。两种方式等价，`scripts/health_report.py` 只认落盘文件。

### 第 3 步：生成报告

```bash
python3 scripts/health_report.py --raw-dir raw --out out --name "用户昵称"
```

产出三个文件：

| 文件 | 用途 |
| --- | --- |
| `out/report.json` | 结构化指标，agent 二次分析用 |
| `out/report.md` | 文字版报告，直接贴给用户看 |
| `out/report.html` | 自包含的可分享报告卡（单文件，内联 CSS/SVG） |

### 第 4 步：解读并交付

读 `out/report.md`，用你自己的话给用户讲三件事，**不要**把 md 原文整段粘贴：

1. **一句话结论**：总分 + 评级 + 最短板是哪一项。
2. **最该马上做的 1-2 件事**：通常来自「速办」级建议（临期券、即将过期积分）。
3. **一个长期的饮食建议**：来自营养维度（钠、饮料热量占比、单餐热量）。

最后把 `out/report.html` 交给用户，说明这是可直接分享的报告卡；用户想要图片时，可以用浏览器把 HTML 截图。

## 数据口径（务必准确）

- **单餐热量按订单汇总**，不是按餐品子项。套餐要拆 `order-list` 里的 `comboItemList` 再累加。
- **营养匹配分四级**，报告里会标注：精确命中 / 近似匹配 / 品类中位数估算 / 未覆盖。带 `≈` 的餐品是估算值，只能讲趋势不能讲精确数值。
- **未覆盖餐品不参与热量推断**，报告底部的「数据可信度」会给出覆盖率。被追问时如实说明覆盖率，不要粉饰。
- **已取消订单不计入消费与热量**，但会计入「取消订单」提醒。
- 积分、券、订单金额全部来自 MCP 实时返回，**不要**自己估算或补充未取到的数据。

## 安全边界（不可越过）

本 Skill 只做只读分析。以下操作**必须**先获得用户明确同意，且要说明会消耗什么：

- `auto-bind-coupons`（一键领券，会占用券额度）
- `draw-lottery`（积分抽奖，真实消耗积分）
- `mall-create-order`（积分兑换，会扣积分与库存）
- `create-order` / `cancel-order`（下单与取消，涉及真实支付）

用户只要「体检报告」，就**不要**调用上面任何一个。报告里提到抽奖、领券、兑换时，只能给出建议，不能代劳。

## 输出约束

- 报告结论不构成医疗、营养建议，页脚已声明，不要额外给出医疗诊断或处方建议。
- 涉及用户账户数据（订单、积分、券）时，不要把完整数据贴到公开渠道或第三方服务。
- 生成的 HTML 是自包含单文件，可以分享；分享前提醒用户其中含个人消费数据。

## 参考

- 评分口径与参考值来源：`references/report-spec.md`
- 报告卡模板：`assets/report_card.html`
