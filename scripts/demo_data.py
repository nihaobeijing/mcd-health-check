#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门健康体检官 · 演示数据生成器

生成一套**完全合成**的 MCP 原始返回，用于：
- 不带 Token 预览报告效果（`health_report.py --demo`）
- 生成 README 里的示例截图（不含任何真实账户数据）

合成数据的格式与麦当劳 MCP Server 的真实返回完全一致，
所以体检引擎跑的是同一条代码路径。
"""
import json
import os

# 营养表：与真实返回同样的紧凑格式
NUTRITION_ROWS = [
    ("猪柳蛋麦满分", 1618, 387, 23, 21, 25, 846, 243),
    ("烟肉蛋麦满分", 1089, 260, 16, 10, 24, 483, 238),
    ("火腿扒麦满分", 1092, 261, 14, 12, 24, 608, 131),
    ("原味板烧鸡腿麦满分", 1029, 246, 15, 9, 25, 611, 133),
    ("麦满分", 1291, 309, 16, 13, 26, 707, 169),
    ("双层吉士汉堡", 1796, 429, 27, 22, 31, 1017, 232),
    ("吉士汉堡包", 1231, 294, 16, 12, 30, 673, 144),
    ("巨无霸", 2146, 513, 27, 26, 42, 961, 171),
    ("板烧鸡腿堡", 1638, 391, 23, 17, 35, 1041, 93),
    ("麦辣鸡腿汉堡", 2029, 485, 24, 24, 42, 1208, 154),
    ("麦香鸡", 1546, 369, 15, 17, 39, 731, 73),
    ("麦香鱼", 1359, 325, 16, 13, 35, 556, 99),
    ("麦乐鸡5块", 890, 213, 12, 12, 13, 422, 9),
    ("麦辣鸡翅-2块", 937, 224, 13, 15, 9, 537, 13),
    ("中薯条", 1210, 289, 4, 12, 38, 165, 18),
    ("小薯条", 877, 210, 3, 9, 28, 120, 13),
    ("脆薯饼", 686, 146, 3, 7, 20, 170, 11),
    ("大杯玉米杯", 365, 87, 4, 1, 12, 2, 10),
    ("圆筒冰淇淋", 391, 93, 2, 3, 14, 36, 77),
    ("香芋派", 971, 232, 2, 12, 28, 159, 7),
    ("朱古力新地", 1178, 282, 5, 9, 44, 126, 182),
    ("可乐大杯", 936, 224, 0, 0, 55, 0, 15),
    ("可乐中杯", 616, 147, 0, 0, 36, 0, 10),
    ("无糖可口可乐中杯", 0, 0, 0, 0, 1, 35, 0),
    ("雪碧中杯", 440, 105, 0, 0, 26, 29, 0),
    ("大杯鲜萃咖啡", 54, 13, 1, 0, 0, 3, 2),
    ("北美招牌牧场酱", 68, 16, 0, 3, 1, 120, 3),
]

# 历史订单：(订单号, 时间, 门店, 状态, 金额, [(商品, [(子项, 数量)])])
DEMO_ORDERS = [
    ("MCD20260914001", "2026-09-14 19:32:11", "麦当劳北京北苑路餐厅", "订单已完成", "14.9",
     [("人气经典随心配", [("双层吉士汉堡", 1), ("中薯条", 1), ("可乐大杯", 1)])]),
    ("MCD20260902002", "2026-09-02 12:41:55", "麦当劳北京北苑路餐厅", "订单已完成", "13.9",
     [("精选超值随心配", [("麦辣鸡腿汉堡", 1), ("脆薯饼", 1), ("无糖可口可乐中杯", 1)])]),
    ("MCD20260821003", "2026-08-21 18:05:47", "麦当劳北京北苑路餐厅", "订单已完成", "27.9",
     [("麦香鱼套餐", [("麦香鱼", 1), ("香芋派", 1), ("雪碧中杯", 1)])]),
    ("MCD20260803004", "2026-08-03 21:47:02", "麦当劳北京望京SOHO餐厅", "订单已完成", "35.8",
     [("巨无霸套餐", [("巨无霸", 1), ("麦乐鸡5块", 1), ("可乐大杯", 1)])]),
    ("MCD20260719005", "2026-07-19 12:02:33", "麦当劳北京北苑路餐厅", "订单已完成", "26.9",
     [("板烧鸡腿堡套餐", [("板烧鸡腿堡", 1), ("中薯条", 1), ("可乐中杯", 1)])]),
    ("MCD20260626006", "2026-06-26 19:11:08", "麦当劳北京北苑路餐厅", "订单已取消", "13.9",
     [("精选超值随心配", [("麦辣鸡腿汉堡", 1), ("香芋派", 1), ("无糖可口可乐中杯", 1)])]),
    ("MCD20260611007", "2026-06-11 09:28:41", "麦当劳北京望京SOHO餐厅", "订单已完成", "27.9",
     [("猪柳蛋麦满分套餐", [("猪柳蛋麦满分", 1), ("大杯鲜萃咖啡", 1)])]),
    ("MCD20260523008", "2026-05-23 18:52:19", "麦当劳北京北苑路餐厅", "订单已完成", "22.9",
     [("麦香鸡套餐", [("麦香鸡", 1), ("圆筒冰淇淋", 1), ("可乐中杯", 1)])]),
    ("MCD20260430009", "2026-04-30 21:26:57", "麦当劳北京北苑路餐厅", "订单已完成", "16.9",
     [("吉士汉堡包套餐", [("吉士汉堡包", 1), ("脆薯饼", 1), ("可乐中杯", 1)])]),
    ("MCD20260412010", "2026-04-12 12:38:50", "麦当劳北京北苑路餐厅", "订单已完成", "15.9",
     [("火腿扒麦满分套餐", [("火腿扒麦满分", 1), ("中薯条", 1), ("无糖可口可乐中杯", 1)])]),
]

DEMO_ACCOUNT = {
    "availablePoint": "312.5",
    "accountId": "DEMO-ACCOUNT-0001",
    "accumulativePoint": "1420.0",
    "currency": "麦享会积分",
    "currentMouthExpirePoint": "36.5",
    "expiredPoint": "742.0",
    "frozenPoint": "0",
    "lastMouthExpirePoint": "0",
    "nextMouthExpirePoint": "0",
    "usedPoint": "365.5",
}

DEMO_COUPONS = """# 您的优惠券列表

共 2 张可用优惠券 | 第 1/1 页 | 每页 200 条

## 14.9元板烧鸡腿堡套餐
- **优惠**: ¥14.9 (用券价格)
- **有效期**: 2026-10-01 10:30-2026-10-25 23:59 周一、二、三、四、五 10:30-23:59
- **领取时间**: 5日前收到
- **标签**: 到店专用、外送专用

## 19.9元麦辣三件套
- **优惠**: ¥19.9 (用券价格)
- **有效期**: 2026-10-01 10:30-2026-10-25 23:59 周一、二、三、四、五 10:30-23:59
- **领取时间**: 5日前收到
- **标签**: 到店专用、外送专用
"""

DEMO_MALL_ORDERS = [{
    "hasNext": False,
    "lastId": 0,
    "list": [
        {"orderId": "ECS1208114019621048320", "orderStatus": 30, "orderStatusTitle": "已完成",
         "totalCount": 1, "goods": [{"type": 0, "spuId": 16132, "skuId": 16822,
                                     "spuName": "积分兑换芝士片礼盒", "skuName": "", "count": 1, "points": "100"}]},
        {"orderId": "ECS528859818162417666", "orderStatus": 30, "orderStatusTitle": "已完成",
         "totalCount": 1, "goods": [{"type": 0, "spuId": 14767, "skuId": 15441,
                                     "spuName": "枫糖风味燕麦拿铁兑换券", "skuName": "", "count": 1, "points": "150"}]},
    ],
}]

DEMO_LOTTERY = {
    "activityCode": "dtx2",
    "activityStatusText": "进行中",
    "activityName": "麦麦积分抽奖",
    "beginTime": "2025-01-26 00:00:00",
    "endTime": "2030-12-31 23:59:59",
    "drawPoint": "24",
    "drawTypeText": "消耗积分抽奖",
    "availablePoint": "312.5",
    "drawDecision": {"resourceEligible": True,
                     "nextConsumption": {"type": "POINTS", "points": "24", "chances": 0,
                                         "text": "本次将消耗 24 积分"}},
    "prizes": [
        {"name": "下单立减3元券", "typeText": "优惠券"},
        {"name": "麦辣三件套5折券", "typeText": "优惠券"},
        {"name": "麦旋风5折券", "typeText": "优惠券"},
        {"name": "30积分", "typeText": "积分奖"},
    ],
}

DEMO_CAMPAIGN = """# 活动日历

#### 2026年10月24日

-   **活动标题**：🧡「麦门挚友」秋季上新
    **活动内容介绍**：多款秋日风味回归，
    全新麦门挚友套餐上线，
    扫码即可解锁专属好价～

#### 2026年11月1日

-   **活动标题**：🩶灰白撞色，灰焰圆筒酷爽登场
    **活动内容介绍**：灰焰圆筒酷爽上新！
    浓郁香草味碰上酷灰脆筒，灰白撞色吸睛。
"""


def _wrap(payload):
    """把工具返回包成 MCP 的文本形态（结构说明 + Original Response）。"""
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = json.dumps(dict({"success": True, "code": 200, "message": "请求成功",
                            "datetime": now, "traceId": "demo-trace", "data": payload}),
                       ensure_ascii=False)
    return ("# API Response Information\n\n"
            "Below is the response from an API call. To help you understand the data, "
            "I've provided:\n\n"
            "1. A detailed description of all fields in the response structure\n"
            "2. The complete API response\n\n"
            "## Response Structure\n\n"
            "## Original Response\n\n" + body + "\n")


def generate(out_dir):
    """把一整套合成原始返回写到 out_dir，返回该目录。"""
    os.makedirs(out_dir, exist_ok=True)

    def write(name, text):
        with open(os.path.join(out_dir, name + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(text)

    nutrition = "[%d]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:\n" % len(
        NUTRITION_ROWS)
    for name, kj, kcal, pro, fat, carb, na, ca in NUTRITION_ROWS:
        nutrition += "  %s,null,%d,%d,%d,%d,%d,%d,%d\n" % (name, kj, kcal, pro, fat, carb, na, ca)

    orders = []
    for order_id, create_time, store, status, amount, products in DEMO_ORDERS:
        product_list = []
        for product_name, combos in products:
            product_list.append({
                "productCode": "990001%04d" % (len(product_list) + 1),
                "productName": product_name,
                "quantity": 1,
                "comboItemList": [{"name": name, "productCode": "%04d" % (1000 + i),
                                   "quantity": qty} for i, (name, qty) in enumerate(combos)],
            })
        orders.append({
            "orderId": order_id,
            "createTime": create_time,
            "orderType": "1",
            "beType": "1",
            "beCode": "",
            "storeCode": "12345",
            "storeName": store,
            "orderStatus": status,
            "orderProductList": product_list,
            "realTotalAmount": amount,
        })

    write("now-time-info", _wrap({
        "timestamp": 1792800000000,
        "datetime": "2026-10-22T12:00:00.000",
        "formatted": "2026-10-22 12:00:00",
        "date": "2026-10-22", "year": 2026, "month": 10, "day": 22,
        "dayOfWeek": "THURSDAY", "timezone": "GMT+08:00", "offset": "+08:00",
        "utc": "2026-10-22T04:00:00.000Z",
    }))
    write("order-list", _wrap({"list": orders}))
    write("list-nutrition-foods", _wrap(nutrition))
    write("query-my-account", _wrap(DEMO_ACCOUNT))
    write("query-my-coupons", DEMO_COUPONS)
    write("mall-order-list", _wrap(DEMO_MALL_ORDERS))
    write("query-lottery-info", _wrap(DEMO_LOTTERY))
    write("campaign-calendar", DEMO_CAMPAIGN)
    return out_dir


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "raw-demo"
    print("演示数据已生成：%s" % os.path.abspath(generate(target)))
