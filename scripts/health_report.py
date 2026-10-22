#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门健康体检官 —— 体检引擎

输入：麦当劳 MCP 工具的原始返回文本（按工具名命名存放的文件）
输出：体检报告 JSON + Markdown 报告 + 可分享 HTML 报告卡

设计原则：
1. 数据只来自 MCP 官方工具，脚本不臆造任何数值；
2. 营养估算分级标注（精确 / 近似 / 品类中位 / 未覆盖），报告公开数据覆盖率；
3. 只读分析，绝不发起领券、抽奖、下单等消耗型操作。

用法：
    python3 health_report.py --raw-dir raw/ --out out/
    python3 health_report.py --raw-dir raw/ --out out/ --name "小明"
"""
import argparse
import datetime
import html
import json
import math
import os
import re
import statistics
from string import Template

# ---------------------------------------------------------------- 基准参考值
# 中国居民膳食指南(2022) 轻体力活动水平：每日能量 2000kcal 上下
REF_DAILY_KCAL = 2000.0
REF_MEAL_KCAL = 700.0          # 单餐建议上限
REF_DAILY_SODIUM_MG = 2000.0   # WHO 每日钠摄入建议上限
REF_DAILY_PROTEIN_G = 60.0     # 每日蛋白质参考摄入
REF_DAILY_FAT_G = 60.0         # 每日脂肪参考摄入
REF_DAILY_CARB_G = 300.0       # 每日碳水参考摄入
REF_FAT_ENERGY_RATIO = 0.30    # 脂肪供能比上限
REF_PROTEIN_ENERGY_RATIO = 0.10  # 蛋白供能比下限
REF_MONTHLY_BUDGET = 200.0     # 月均消费理性基准
REF_IMPULSE_ORDER = 100.0      # 单笔超过此金额视为冲动大额

# 品类判定关键词（按顺序命中）
CATEGORY_RULES = [
    ("condiment", ["酱"]),
    ("drink", ["可乐", "雪碧", "咖啡", "红茶", "绿茶", "橙汁", "果汁", "奶茶", "奶昔", "柠檬", "苏打", "水"]),
    ("dessert", ["派", "冰淇淋", "圣代", "麦旋风", "新地", "圆筒", "布丁", "蛋糕", "蛋筒", "甜筒"]),
    ("side", ["薯条", "薯饼", "玉米杯", "脆薯", "小食", "鸡米花", "上校鸡块"]),
    ("chicken", ["麦乐鸡", "麦香鸡", "麦香鱼", "鸡腿", "鸡翅", "鸡块", "炸鸡", "鸡柳", "鸡排", "鸡"]),
    ("breakfast", ["麦满分", "猪柳蛋", "培根蛋", "火腿扒", "猪柳", "蛋堡", "卷"]),
    ("burger", ["堡", "汉堡", "双层", "吉士", "牛堡"]),
]

CATEGORY_LABELS = {
    "burger": "汉堡",
    "chicken": "炸物小食",
    "side": "薯条小食",
    "drink": "饮料",
    "dessert": "甜品",
    "breakfast": "早餐",
    "condiment": "酱料",
    "other": "其他",
}

NIGHT_HOURS = set(range(22, 24)) | set(range(0, 5))
MORNING_HOURS = set(range(5, 11))
NOON_HOURS = set(range(11, 15))
AFTERNOON_HOURS = set(range(15, 18))
EVENING_HOURS = set(range(18, 22))

MEAL_SLOTS = [
    ("早餐档", MORNING_HOURS),
    ("午餐档", NOON_HOURS),
    ("下午茶", AFTERNOON_HOURS),
    ("晚餐档", EVENING_HOURS),
    ("深夜档", NIGHT_HOURS),
]


# ---------------------------------------------------------------- 原始数据解析
def read_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def extract_json(text):
    """从 MCP 工具返回文本中提取 JSON。MCP 返回有两种形态：
    - '## Original Response' 之后跟原始 JSON
    - 工具直接返回 markdown 文本（非 JSON）
    """
    if not text:
        return None
    marker = "## Original Response"
    if marker in text:
        tail = text.split(marker, 1)[1].strip()
        tail = tail.strip("`").strip()
        try:
            return json.loads(tail)
        except json.JSONDecodeError:
            start = tail.find("{")
            if start >= 0:
                try:
                    return json.loads(tail[start:])
                except json.JSONDecodeError:
                    return None
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None
    return None


def parse_nutrition(data_text):
    """解析 list-nutrition-foods 返回的紧凑营养表。

    形如：
      [158]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
        猪柳麦满分,null,1288,308,16,16,24,781,213
    """
    table = {}
    for line in (data_text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("[") or line.startswith("{"):
            continue
        parts = [p.strip() for p in line.split(",")]
        name = parts[0]
        if not name:
            continue
        nums = []
        for token in parts[1:]:
            try:
                nums.append(float(token))
            except ValueError:
                continue
        if len(nums) < 7:
            continue
        kj, kcal, protein, fat, carb, sodium, calcium = nums[-7:]
        table[name] = {
            "name": name,
            "kj": kj,
            "kcal": kcal,
            "protein": protein,
            "fat": fat,
            "carb": carb,
            "sodium": sodium,
            "calcium": calcium,
        }
    return table


def normalize(name):
    """归一化餐品名，用于近似匹配。"""
    text = name.strip()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)
    text = text.replace("的", "")
    return text


def classify(name):
    """判定餐品品类。"""
    for category, keywords in CATEGORY_RULES:
        for keyword in keywords:
            if keyword in name:
                return category
    return "other"


def build_category_index(table):
    """按品类汇总营养表条目，供估算使用。"""
    index = {}
    for entry in table.values():
        index.setdefault(classify(entry["name"]), []).append(entry)
    return index


# ---------------------------------------------------------------- 营养匹配
def match_nutrition(name, table, category_index):
    """把一个餐品名匹配到营养表条目。

    返回 (match_type, entry, note)：
      exact    精确命中
      approx   近似命中（包含关系）
      estimate 品类中位数估算
      condiment 调味酱，按 0 热量计
      unknown  无法覆盖
    """
    if name in table:
        return "exact", table[name], None

    norm = normalize(name)
    for entry_name, entry in table.items():
        if normalize(entry_name) == norm:
            return "exact", entry, None

    # 调味酱：热量贡献极低，计入已知
    if classify(name) == "condiment":
        return "condiment", {
            "name": name, "kj": 0, "kcal": 0, "protein": 0,
            "fat": 0, "carb": 0, "sodium": 0, "calcium": 0,
        }, "调味酱，按 0 热量计入"

    # 包含关系近似：营养表条目名是餐品名的子串（或反之），且长度占比足够
    best = None
    for entry_name, entry in table.items():
        norm_entry = normalize(entry_name)
        if len(norm_entry) < 3:
            continue
        if norm_entry in norm or (len(norm) >= 4 and norm in norm_entry):
            coverage = len(norm_entry) / max(len(norm), 1)
            if coverage >= 0.5 and (best is None or coverage > best[0]):
                best = (coverage, entry)
    if best:
        return "approx", best[1], "按同类单品估算（%s）" % best[1]["name"]

    # 品类中位数估算
    category = classify(name)
    pool = category_index.get(category) or []
    if pool:
        kcal = statistics.median([p["kcal"] for p in pool])
        protein = statistics.median([p["protein"] for p in pool])
        fat = statistics.median([p["fat"] for p in pool])
        carb = statistics.median([p["carb"] for p in pool])
        sodium = statistics.median([p["sodium"] for p in pool])
        calcium = statistics.median([p["calcium"] for p in pool])
        return "estimate", {
            "name": name, "kj": kcal * 4.184, "kcal": kcal, "protein": protein,
            "fat": fat, "carb": carb, "sodium": sodium, "calcium": calcium,
        }, "按品类中位数估算（%s）" % category
    return "unknown", None, None


# ---------------------------------------------------------------- 数据聚合
def parse_orders(order_json):
    """从 order-list 返回中取出订单列表。"""
    if not order_json:
        return []
    data = order_json.get("data") or {}
    if isinstance(data, dict):
        return data.get("list") or []
    if isinstance(data, list):
        return data
    return []


def parse_datetime(order):
    raw = (order.get("createTime") or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    return None


def collect_items(orders, table, category_index):
    """展开订单里的商品与套餐子项，逐项匹配营养。"""
    records = []
    for order in orders:
        for product in order.get("orderProductList") or []:
            combos = product.get("comboItemList") or []
            if combos:
                for combo in combos:
                    records.append({
                        "order_id": order.get("orderId"),
                        "create_time": order.get("createTime"),
                        "order_status": order.get("orderStatus"),
                        "parent": product.get("productName"),
                        "name": combo.get("name") or product.get("productName"),
                        "quantity": combo.get("quantity") or 1,
                    })
            else:
                records.append({
                    "order_id": order.get("orderId"),
                    "create_time": order.get("createTime"),
                    "order_status": order.get("orderStatus"),
                    "parent": product.get("productName"),
                    "name": product.get("productName"),
                    "quantity": product.get("quantity") or 1,
                })

    for record in records:
        match_type, entry, note = match_nutrition(record["name"], table, category_index)
        record["match_type"] = match_type
        record["note"] = note
        record["category"] = classify(record["name"])
        if entry:
            quantity = record["quantity"] or 1
            record["kcal"] = entry["kcal"] * quantity
            record["protein"] = entry["protein"] * quantity
            record["fat"] = entry["fat"] * quantity
            record["carb"] = entry["carb"] * quantity
            record["sodium"] = entry["sodium"] * quantity
            record["calcium"] = entry["calcium"] * quantity
        else:
            for key in ("kcal", "protein", "fat", "carb", "sodium", "calcium"):
                record[key] = 0.0
    return records


def slot_of(moment):
    if moment is None:
        return "未知"
    hour = moment.hour
    for label, hours in MEAL_SLOTS:
        if hour in hours:
            return label
    return "未知"


def analyze(orders, items, account, mall_orders, coupons_text, lottery, campaign_text, now):
    """计算全部体检指标。"""
    completed = [o for o in orders if "取消" not in (o.get("orderStatus") or "")]
    cancelled = [o for o in orders if "取消" in (o.get("orderStatus") or "")]
    done_items = [i for i in items if "取消" not in (i.get("order_status") or "")]

    # ---- 营养 ----
    total_kcal = sum(i["kcal"] for i in done_items)
    total_protein = sum(i["protein"] for i in done_items)
    total_fat = sum(i["fat"] for i in done_items)
    total_carb = sum(i["carb"] for i in done_items)
    total_sodium = sum(i["sodium"] for i in done_items)
    total_calcium = sum(i["calcium"] for i in done_items)
    item_count = len(done_items)
    # 单餐口径：热量按订单汇总，而不是按餐品子项
    order_kcal = {}
    order_sodium = {}
    for item in done_items:
        order_id = item.get("order_id")
        order_kcal[order_id] = order_kcal.get(order_id, 0.0) + item["kcal"]
        order_sodium[order_id] = order_sodium.get(order_id, 0.0) + item["sodium"]
    meal_count = len(order_kcal)
    avg_kcal = total_kcal / meal_count if meal_count else 0.0
    avg_sodium = total_sodium / meal_count if meal_count else 0.0
    max_kcal_order = max(order_kcal.values()) if order_kcal else 0.0

    matched = [i for i in done_items if i["match_type"] in ("exact", "condiment")]
    approx = [i for i in done_items if i["match_type"] == "approx"]
    estimated = [i for i in done_items if i["match_type"] == "estimate"]
    unknown = [i for i in done_items if i["match_type"] == "unknown"]
    known_ratio = (len(matched) + len(approx)) / item_count if item_count else 0.0
    exact_ratio = len(matched) / item_count if item_count else 0.0

    energy_from = {"protein": total_protein * 4, "fat": total_fat * 9, "carb": total_carb * 4}
    energy_base = sum(energy_from.values()) or 1.0
    ratios = {k: v / energy_base for k, v in energy_from.items()}

    # ---- 时间维度 ----
    moments = [parse_datetime(o) for o in completed]
    moments = [m for m in moments if m]
    slots = {}
    for moment in moments:
        slots[slot_of(moment)] = slots.get(slot_of(moment), 0) + 1
    night_ratio = slots.get("深夜档", 0) / len(completed) if completed else 0.0

    # ---- 钱包 ----
    def amount(order):
        try:
            return float(order.get("realTotalAmount") or 0)
        except (TypeError, ValueError):
            return 0.0

    total_spend = sum(amount(o) for o in completed)
    cancelled_spend = sum(amount(o) for o in cancelled)
    avg_ticket = total_spend / len(completed) if completed else 0.0
    impulse_orders = [o for o in completed if amount(o) > REF_IMPULSE_ORDER]
    stores = {}
    for order in completed:
        name = order.get("storeName") or "未知门店"
        stores[name] = stores.get(name, 0) + 1
    top_stores = sorted(stores.items(), key=lambda kv: -kv[1])
    store_concentration = (top_stores[0][1] / len(completed)) if (top_stores and completed) else 0.0

    # 消费周期（天）与月均
    active_days = len({m.date() for m in moments})
    span_days = 0
    if moments:
        span_days = (max(moments) - min(moments)).days + 1
    months = max(span_days / 30.44, 1.0)
    monthly_spend = total_spend / months
    orders_per_month = len(completed) / months

    # 复购单品
    dish_counter = {}
    for item in done_items:
        entry = dish_counter.setdefault(item["name"], {"count": 0, "match_type": item["match_type"]})
        entry["count"] += (item["quantity"] or 1)
    top_dishes = sorted(dish_counter.items(), key=lambda kv: -kv[1]["count"])[:5]

    # 品类热量分布
    category_kcal = {}
    for item in done_items:
        category_kcal[item["category"]] = category_kcal.get(item["category"], 0) + item["kcal"]
    drink_ratio = category_kcal.get("drink", 0) / total_kcal if total_kcal else 0.0
    top_category_ratio = (max(category_kcal.values()) / total_kcal) if (total_kcal and category_kcal) else 0.0
    top_category_name = max(category_kcal.items(), key=lambda kv: kv[1])[0] if category_kcal else "—"
    top_category_label = CATEGORY_LABELS.get(top_category_name, top_category_name)

    # ---- 积分与权益 ----
    points = {
        "available": _to_float((account or {}).get("availablePoint")),
        "accumulative": _to_float((account or {}).get("accumulativePoint")),
        "used": _to_float((account or {}).get("usedPoint")),
        "expired": _to_float((account or {}).get("expiredPoint")),
        "frozen": _to_float((account or {}).get("frozenPoint")),
        "expiring_this_month": _to_float((account or {}).get("currentMouthExpirePoint")),
    }
    points["expired_ratio"] = points["expired"] / points["accumulative"] if points["accumulative"] else 0.0
    points["redeem_ratio"] = points["used"] / points["accumulative"] if points["accumulative"] else 0.0

    now_dt = now or datetime.datetime.now()
    coupons = parse_coupons(coupons_text, now_dt)
    lottery_info = (lottery or {}).get("data") or {}
    mall = parse_mall(mall_orders)
    expiring_coupons = [c for c in coupons if c["days_left"] <= 3 and c["days_left"] >= 0]

    # ---- 评分 ----
    nutrition_score = 100.0
    if avg_kcal > REF_MEAL_KCAL:
        nutrition_score -= min(35.0, (avg_kcal - REF_MEAL_KCAL) / 15.0)
    if avg_sodium > REF_DAILY_SODIUM_MG * 0.35:
        nutrition_score -= min(25.0, (avg_sodium - REF_DAILY_SODIUM_MG * 0.35) / 12.0)
    if ratios["fat"] > REF_FAT_ENERGY_RATIO:
        nutrition_score -= min(20.0, (ratios["fat"] - REF_FAT_ENERGY_RATIO) * 150)
    if ratios["protein"] < REF_PROTEIN_ENERGY_RATIO:
        nutrition_score -= min(15.0, (REF_PROTEIN_ENERGY_RATIO - ratios["protein"]) * 200)
    if drink_ratio > 0.35:
        nutrition_score -= min(15.0, (drink_ratio - 0.35) * 120)
    nutrition_score = max(0.0, min(100.0, nutrition_score))

    wallet_score = 100.0
    cancel_ratio = len(cancelled) / len(orders) if orders else 0.0
    if cancel_ratio > 0.1:
        wallet_score -= min(30.0, (cancel_ratio - 0.1) * 200)
    if monthly_spend > REF_MONTHLY_BUDGET:
        wallet_score -= min(25.0, (monthly_spend - REF_MONTHLY_BUDGET) / 8.0)
    if impulse_orders:
        wallet_score -= min(20.0, len(impulse_orders) * 8.0)
    if avg_ticket > 50:
        wallet_score -= min(15.0, (avg_ticket - 50) * 0.8)
    wallet_score = max(0.0, min(100.0, wallet_score))

    entitlement_score = 100.0
    if points["expired_ratio"] > 0.2:
        entitlement_score -= min(35.0, (points["expired_ratio"] - 0.2) * 110)
    if expiring_coupons:
        entitlement_score -= min(18.0, len(expiring_coupons) * 6.0)
    if points["expiring_this_month"] > 0:
        entitlement_score -= min(15.0, points["expiring_this_month"] / 4.0)
    if points["accumulative"] and points["available"] / points["accumulative"] < 0.4:
        entitlement_score -= min(10.0, (0.4 - points["available"] / points["accumulative"]) * 40)
    entitlement_score = max(0.0, min(100.0, entitlement_score))

    habit_score = 100.0
    if top_category_ratio > 0.6:
        habit_score -= min(25.0, (top_category_ratio - 0.6) * 90)
    if night_ratio > 0.3:
        habit_score -= min(20.0, (night_ratio - 0.3) * 100)
    dish_variety = len(dish_counter) / len(completed) if completed else 0
    if dish_variety < 1.2:
        habit_score -= min(20.0, (1.2 - dish_variety) * 25)
    if len(completed) and active_days and active_days < len(completed) * 0.7:
        habit_score -= 10.0
    habit_score = max(0.0, min(100.0, habit_score))

    # 某一维度依赖的数据缺失时，该维度不计分，也不参与加权平均
    has_orders = bool(completed)
    has_account = bool(account)
    has_nutrition = any(i["match_type"] != "unknown" for i in items)
    scores = {
        "nutrition": nutrition_score if (has_orders and has_nutrition) else None,
        "wallet": wallet_score if has_orders else None,
        "entitlement": entitlement_score if has_account else None,
        "habit": habit_score if has_orders else None,
    }
    weights = {"nutrition": 0.30, "wallet": 0.20, "entitlement": 0.25, "habit": 0.25}
    valid = {key: value for key, value in scores.items() if value is not None}
    total_score = None
    if valid:
        total_score = (sum(valid[key] * weights[key] for key in valid)
                       / sum(weights[key] for key in valid))
    grade = grade_of(total_score) if total_score is not None else "—"

    metrics = {
        "generated_at": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "score": round(total_score, 1) if total_score is not None else None,
        "grade": grade,
        "data_sufficient": bool(valid),
        "missing_dimensions": [key for key, value in scores.items() if value is None],
        "dimensions": {
            key: (round(value, 1) if value is not None else None)
            for key, value in scores.items()
        },
        "nutrition": {
            "total_kcal": round(total_kcal, 1),
            "avg_kcal_per_order": round(avg_kcal, 1),
            "max_kcal_order": round(max_kcal_order, 1),
            "avg_sodium_per_order_mg": round(avg_sodium, 1),
            "meal_count": meal_count,
            "total_protein_g": round(total_protein, 1),
            "total_fat_g": round(total_fat, 1),
            "total_carb_g": round(total_carb, 1),
            "total_sodium_mg": round(total_sodium, 1),
            "total_calcium_mg": round(total_calcium, 1),
            "energy_ratios": {k: round(v, 4) for k, v in ratios.items()},
            "drink_energy_ratio": round(drink_ratio, 4),
            "top_category": top_category_label,
            "top_category_key": top_category_name,
            "top_category_ratio": round(top_category_ratio, 4),
            "category_kcal": {
                CATEGORY_LABELS.get(k, k): round(v, 1)
                for k, v in sorted(category_kcal.items(), key=lambda kv: -kv[1])
            },
        },
        "coverage": {
            "items_total": item_count,
            "exact": len(matched),
            "approx": len(approx),
            "estimated": len(estimated),
            "unknown": len(unknown),
            "exact_ratio": round(exact_ratio, 4),
            "known_ratio": round(known_ratio, 4),
            "unknown_names": sorted({i["name"] for i in unknown}),
            "estimated_names": sorted({i["name"] for i in estimated}),
        },
        "wallet": {
            "total_spend": round(total_spend, 2),
            "order_count": len(completed),
            "cancelled_count": len(cancelled),
            "cancelled_spend": round(cancelled_spend, 2),
            "avg_ticket": round(avg_ticket, 2),
            "monthly_spend": round(monthly_spend, 2),
            "orders_per_month": round(orders_per_month, 2),
            "impulse_orders": len(impulse_orders),
            "top_stores": [{"name": n, "count": c} for n, c in top_stores[:3]],
            "store_concentration": round(store_concentration, 4),
            "top_dishes": [
                {"name": n, "count": e["count"], "estimated": e["match_type"] in ("approx", "estimate")}
                for n, e in top_dishes
            ],
            "span_days": span_days,
            "active_days": active_days,
        },
        "habit": {
            "slots": slots,
            "night_ratio": round(night_ratio, 4),
            "dish_variety_per_order": round(dish_variety, 2),
        },
        "points": points,
        "coupons": {
            "count": len(coupons),
            "expiring_soon": expiring_coupons,
            "items": coupons,
        },
        "lottery": {
            "activity_name": lottery_info.get("activityName"),
            "activity_status": lottery_info.get("activityStatusText"),
            "draw_point": lottery_info.get("drawPoint"),
            "prizes": [p.get("name") for p in (lottery_info.get("prizes") or [])][:6],
        },
        "mall": mall,
        "campaign": parse_campaign(campaign_text),
    }
    metrics["advice"] = build_advice(metrics, now_dt)
    return metrics


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def grade_of(score):
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def parse_coupons(text, now_dt=None):
    """从 query-my-coupons 的 markdown 返回里解析券。"""
    coupons = []
    if not text:
        return coupons
    today = (now_dt or datetime.datetime.now()).date()
    lines = text.splitlines()
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if current:
                coupons.append(current)
            current = {"name": stripped[3:].strip(), "price": None, "expire": None, "days_left": 9999}
        elif current is not None:
            match = re.search(r"¥\s*([\d.]+)", stripped)
            if match and current["price"] is None:
                current["price"] = float(match.group(1))
            match = re.search(
                r"\*\*有效期\*\*:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*[-–—~至]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})",
                stripped)
            if match:
                current["expire"] = match.group(2).strip()
                current["start"] = match.group(1).strip()
                try:
                    end = datetime.datetime.strptime(match.group(2).strip(), "%Y-%m-%d %H:%M")
                except ValueError:
                    try:
                        end = datetime.datetime.strptime(match.group(2).strip(), "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        end = None
                if end:
                    current["expire_at"] = end.strftime("%Y-%m-%d %H:%M")
                    current["days_left"] = (end.date() - today).days
    if current:
        coupons.append(current)
    return coupons


def parse_mall(mall_json):
    """解析麦麦商城订单。"""
    orders = []
    if not mall_json:
        return {"count": 0, "points_spent": 0.0, "items": []}
    data = mall_json.get("data") or []
    if isinstance(data, dict):
        data = [data]
    for page in data:
        for order in (page or {}).get("list", []):
            for good in order.get("goods", []) or []:
                orders.append({
                    "name": good.get("spuName"),
                    "count": good.get("count"),
                    "points": _to_float(good.get("points")),
                    "status": order.get("orderStatusTitle"),
                    "order_id": order.get("orderId"),
                })
    return {
        "count": len(orders),
        "points_spent": round(sum(o["points"] for o in orders), 1),
        "items": orders,
    }


def parse_campaign(text):
    """从活动日历 markdown 里抽取活动标题（去重、保持顺序）。"""
    titles = []
    seen = set()
    if not text:
        return {"count": 0, "titles": []}
    for line in text.splitlines():
        match = re.search(r"\*\*活动标题\*\*：\s*(.+)", line.strip())
        if match:
            title = match.group(1).strip()
            if title and title not in seen:
                seen.add(title)
                titles.append(title)
    return {"count": len(titles), "titles": titles[:8]}


# ---------------------------------------------------------------- 建议生成
def build_advice(metrics, now_dt):
    advice = []
    coupons = metrics["coupons"]
    points = metrics["points"]
    nutrition = metrics["nutrition"]
    wallet = metrics["wallet"]
    habit = metrics["habit"]

    for coupon in coupons["expiring_soon"]:
        days = coupon["days_left"]
        when = "今天就过期" if days <= 0 else "还剩 %d 天" % days
        advice.append({
            "level": "urgent",
            "title": "%s（%s）" % (coupon["name"], when),
            "detail": "你的账户里有这张券还没用，%s。去常去的门店点单时优先用掉，别让它白白过期。" % when,
        })

    if points["expiring_this_month"] > 0:
        advice.append({
            "level": "urgent",
            "title": "本月有 %g 积分要过期" % points["expiring_this_month"],
            "detail": "本月即将过期的积分可以直接在麦麦商城兑换实物，先用掉再攒。",
        })

    if points["expired_ratio"] > 0.2:
        advice.append({
            "level": "warning",
            "title": "累计 %g 积分里已有 %g 过期" % (points["accumulative"], points["expired"]),
            "detail": "过期比例 %.0f%%。积分不像现金，不花就会清零，建议设一个「看到积分就先换」的固定习惯。"
                      % (points["expired_ratio"] * 100),
        })

    if nutrition["avg_sodium_per_order_mg"] > REF_DAILY_SODIUM_MG * 0.35:
        advice.append({
            "level": "warning",
            "title": "单餐平均钠摄入 %g mg" % nutrition["avg_sodium_per_order_mg"],
            "detail": "每日钠建议上限 %d mg，单餐占到 %.0f%%。把大杯可乐换成无糖中杯，或把薯条换成玉米杯，单餐能少几百毫克钠。"
                      % (REF_DAILY_SODIUM_MG, nutrition["avg_sodium_per_order_mg"] / REF_DAILY_SODIUM_MG * 100),
        })

    if nutrition["drink_energy_ratio"] > 0.35:
        advice.append({
            "level": "warning",
            "title": "饮料贡献了 %.0f%% 的热量" % (nutrition["drink_energy_ratio"] * 100),
            "detail": "把其中一半订单换成无糖可乐或玉米杯，热量能直接砍掉一大截。",
        })

    if habit["night_ratio"] > 0.3:
        advice.append({
            "level": "info",
            "title": "%.0f%% 的订单发生在深夜档" % (habit["night_ratio"] * 100),
            "detail": "深夜下单多是加班或嘴馋。试试把最后一单换成小食，而不是完整套餐。",
        })

    if wallet["cancelled_count"]:
        advice.append({
            "level": "info",
            "title": "有 %d 单被取消（¥%.1f）" % (wallet["cancelled_count"], wallet["cancelled_spend"]),
            "detail": "占总消费 %.0f%%。下单前先确认门店营业状态和优惠可用性，能省下重复下单的时间。"
                      % (wallet["cancelled_spend"] / wallet["total_spend"] * 100 if wallet["total_spend"] else 0),
        })

    campaign = metrics["campaign"]
    if campaign["count"]:
        advice.append({
            "level": "info",
            "title": "活动日历里有 %d 个活动" % campaign["count"],
            "detail": "进行中与即将到来的活动：%s。挑一个常去门店能买到的试试，比重复点老套餐更有新鲜感。"
                      % "、".join(t[:18] for t in campaign["titles"][:3]),
        })

    if metrics["lottery"].get("draw_point"):
        advice.append({
            "level": "info",
            "title": "积分抽奖每次 %s 分" % metrics["lottery"]["draw_point"],
            "detail": "当前可用积分 %g 分，约够抽 %d 次。抽奖会真实消耗积分，需要你点头才动手。"
                      % (points["available"], int(points["available"] // _to_float(metrics["lottery"]["draw_point"]))),
        })

    order = {"urgent": 0, "warning": 1, "info": 2}
    advice.sort(key=lambda a: order.get(a["level"], 3))
    return advice


# ---------------------------------------------------------------- 渲染
def render_markdown(metrics, name):
    nutrition = metrics["nutrition"]
    wallet = metrics["wallet"]
    points = metrics["points"]
    coverage = metrics["coverage"]
    lines = []
    lines.append("# 麦门健康体检报告 · %s" % (name or "匿名麦门人"))
    lines.append("")
    score_text = ("%s（%s）" % (metrics["score"], metrics["grade"])
                  if metrics["score"] is not None else "数据不足")
    lines.append("生成时间：%s ｜ 麦门健康分：**%s**" % (metrics["generated_at"], score_text))
    if metrics["missing_dimensions"]:
        labels = {"nutrition": "营养均衡", "wallet": "钱包健康",
                  "entitlement": "权益把控", "habit": "习惯结构"}
        missing = "、".join(labels.get(k, k) for k in metrics["missing_dimensions"])
        lines.append("")
        lines.append("> 以下维度因缺少数据未参与评分：%s" % missing)
    lines.append("")
    lines.append("| 维度 | 得分 |")
    lines.append("| --- | --- |")
    for key, label in (("nutrition", "营养均衡"), ("wallet", "钱包健康"),
                       ("entitlement", "权益把控"), ("habit", "习惯结构")):
        value = metrics["dimensions"][key]
        lines.append("| %s | %s |" % (label, ("%.1f" % value) if value is not None else "数据不足"))
    lines.append("")
    lines.append("## 一、营养体检")
    lines.append("")
    lines.append("- 累计摄入 **%s kcal**，单餐平均 **%.0f kcal**（单餐建议上限 %d kcal）"
                 % (format_number(nutrition["total_kcal"]), nutrition["avg_kcal_per_order"], REF_MEAL_KCAL))
    lines.append("- 单餐平均钠 **%.0f mg**（每日建议上限 %d mg）" % (nutrition["avg_sodium_per_order_mg"], REF_DAILY_SODIUM_MG))
    lines.append("- 三大营养素供能比：蛋白质 %.0f%% ｜ 脂肪 %.0f%% ｜ 碳水 %.0f%%"
                 % (nutrition["energy_ratios"]["protein"] * 100,
                    nutrition["energy_ratios"]["fat"] * 100,
                    nutrition["energy_ratios"]["carb"] * 100))
    lines.append("- 饮料贡献热量 **%.0f%%**；热量最集中的品类是 **%s（%.0f%%）**"
                 % (nutrition["drink_energy_ratio"] * 100, nutrition["top_category"], nutrition["top_category_ratio"] * 100))
    lines.append("")
    lines.append("## 二、钱包体检")
    lines.append("")
    lines.append("- 有效订单 **%d 单**，累计消费 **¥%.1f**，客单价 **¥%.1f**，月均 **¥%.1f**"
                 % (wallet["order_count"], wallet["total_spend"], wallet["avg_ticket"], wallet["monthly_spend"]))
    lines.append("- 消费周期 %d 天，活跃 %d 天，月均下单 %.1f 次" % (wallet["span_days"], wallet["active_days"], wallet["orders_per_month"]))
    if wallet["top_stores"]:
        lines.append("- 常去门店：%s" % "、".join("%s（%d 次）" % (s["name"], s["count"]) for s in wallet["top_stores"]))
    if wallet["top_dishes"]:
        lines.append("- 复购 TOP：%s" % "、".join(
            "%s×%d" % (("≈ " if d.get("estimated") else "") + d["name"], d["count"])
            for d in wallet["top_dishes"][:5]))
        lines.append("- 带 ≈ 的餐品热量为品类估算值，仅供趋势参考")
    lines.append("- 取消订单 %d 单（¥%.1f）" % (wallet["cancelled_count"], wallet["cancelled_spend"]))
    lines.append("")
    lines.append("## 三、权益体检")
    lines.append("")
    lines.append("- 积分：可用 **%g** ｜ 累计 %g ｜ 已用 %g ｜ 已过期 %g（占 %.0f%%）"
                 % (points["available"], points["accumulative"], points["used"], points["expired"], points["expired_ratio"] * 100))
    lines.append("- 优惠券 %d 张，其中 %d 张 3 天内过期" % (metrics["coupons"]["count"], len(metrics["coupons"]["expiring_soon"])))
    lines.append("- 积分商城兑换 %d 笔，共消耗 %g 积分" % (metrics["mall"]["count"], metrics["mall"]["points_spent"]))
    lines.append("")
    lines.append("## 四、数据可信度")
    lines.append("")
    lines.append("- 营养匹配：精确 %d ｜ 近似 %d ｜ 品类估算 %d ｜ 未覆盖 %d（覆盖 %.0f%%）"
                 % (coverage["exact"], coverage["approx"], coverage["estimated"], coverage["unknown"], coverage["known_ratio"] * 100))
    if coverage["unknown_names"]:
        lines.append("- 未覆盖餐品：%s" % "、".join(coverage["unknown_names"][:8]))
    lines.append("")
    lines.append("## 五、体检建议")
    lines.append("")
    for index, advice in enumerate(metrics["advice"], 1):
        lines.append("%d. **[%s] %s** — %s" % (index, advice["level"].upper(), advice["title"], advice["detail"]))
    lines.append("")
    lines.append("---")
    lines.append("本报告由「麦门健康体检官 mcd-health-check」生成，全部数据来自麦当劳官方 MCP Server 实时返回。")
    return "\n".join(lines) + "\n"


def format_number(value):
    if value >= 10000:
        return "%.1f 万" % (value / 10000)
    return "%d" % value


def _load_template():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "report_card.html")
    with open(path, "r", encoding="utf-8") as fh:
        return Template(fh.read())


def _esc(text):
    return html.escape(str(text if text is not None else ""))


def _big_ring(score):
    circumference = 2 * math.pi * 52
    if score is None:
        arc = ""
        center = "—"
    else:
        dash = circumference * max(0.0, min(100.0, score)) / 100
        arc = ('<circle cx="60" cy="60" r="52" fill="none" stroke="url(#ringGrad)" stroke-width="10" '
               'stroke-linecap="round" stroke-dasharray="%.2f %.2f" transform="rotate(-90 60 60)"/>'
               % (dash, circumference))
        center = "%.1f" % score
    return (
        '<svg class="ring" viewBox="0 0 120 120">'
        '<defs><linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0%%" stop-color="#FFE38A"/><stop offset="100%%" stop-color="#FFC72C"/>'
        "</linearGradient></defs>"
        '<circle cx="60" cy="60" r="52" fill="none" stroke="rgba(255,255,255,.20)" stroke-width="10"/>'
        + arc +
        '<circle cx="60" cy="60" r="45.5" fill="#fff"/>'
        '<text x="60" y="59" text-anchor="middle" class="ring-num">%s</text>'
        '<text x="60" y="77" text-anchor="middle" class="ring-label">麦门健康分</text>'
        "</svg>" % center
    )


def _mini_ring(value, color):
    circumference = 2 * math.pi * 24
    if value is None:
        arc = ""
        center = "—"
    else:
        dash = circumference * max(0.0, min(100.0, value)) / 100
        arc = ('<circle cx="30" cy="30" r="24" fill="none" stroke="%s" stroke-width="6" '
               'stroke-linecap="round" stroke-dasharray="%.2f %.2f" transform="rotate(-90 30 30)"/>'
               % (color, dash, circumference))
        center = "%.1f" % value
    return (
        '<svg viewBox="0 0 60 60">'
        '<circle cx="30" cy="30" r="24" fill="none" stroke="#F0E9E6" stroke-width="6"/>'
        + arc +
        '<text x="30" y="35.5" text-anchor="middle" font-size="16" font-weight="800" fill="#231F20">%s</text>'
        "</svg>" % center
    )


def _tile(label, value, unit="", cls=""):
    unit_html = "<small>%s</small>" % _esc(unit) if unit else ""
    return '<div class="tile %s"><span>%s</span><b>%s%s</b></div>' % (cls, _esc(label), value, unit_html)


def _metric(label, value_text, pct, color):
    return (
        '<div class="metric"><div class="metric-top"><span>%s</span><b>%s</b></div>'
        '<div class="track"><i style="width:%.1f%%;background:%s"></i></div></div>'
        % (_esc(label), value_text, max(0.0, min(100.0, pct)), color)
    )


DIM_META = [
    ("nutrition", "营养均衡", "#DA291C"),
    ("wallet", "钱包健康", "#E8890C"),
    ("entitlement", "权益把控", "#FFC72C"),
    ("habit", "习惯结构", "#7A5AF8"),
]
ADVICE_ICONS = {"urgent": "🔥", "warning": "⚠️", "info": "💡"}
GRADE_WORD = {"S": "极简自律", "A": "优秀", "B": "良好", "C": "一般", "D": "待改善"}


def render_html(metrics, name):
    nutrition = metrics["nutrition"]
    wallet = metrics["wallet"]
    points = metrics["points"]
    coverage = metrics["coverage"]
    dims = metrics["dimensions"]

    # 头部大环
    ring = _big_ring(metrics["score"])

    # 四维小环
    dim_html = []
    for key, label, color in DIM_META:
        value = dims[key]
        if value is None:
            status = "数据不足"
        elif value >= 85:
            status = "优秀"
        elif value >= 70:
            status = "良好"
        elif value >= 55:
            status = "一般"
        else:
            status = "待改善"
        dim_html.append(
            '<div class="dim">%s<div><div class="dim-name">%s</div>'
            '<div class="dim-val">%s<small>%s</small></div></div></div>'
            % (_mini_ring(value, color), _esc(label),
               ("%.1f" % value) if value is not None else "—", _esc(status))
        )
    dims_html = "".join(dim_html)

    # 结论
    scored = {k: v for k, v in dims.items() if v is not None}
    top_advice = metrics["advice"][0] if metrics["advice"] else None
    if not scored:
        verdict_title = "数据不足，暂无法体检"
        verdict_body = "没有查到可分析的历史订单（可能是账号还没有到店/外送记录），或者 MCP Token 未生效。"
    else:
        weakest = min(scored, key=lambda k: scored[k])
        weakest_label = dict((k, l) for k, l, _ in DIM_META)[weakest]
        verdict_title = "你的麦门画像：%s" % GRADE_WORD.get(metrics["grade"], metrics["grade"])
        verdict_body = "最短板在「%s」（%.1f 分）。%s" % (
            weakest_label, scored[weakest], top_advice["detail"] if top_advice else "保持当前节奏。")

    # 营养
    nutrition_tiles = "".join([
        _tile("累计摄入", format_number(nutrition["total_kcal"]), " kcal"),
        _tile("单餐平均", "%.0f" % nutrition["avg_kcal_per_order"], " kcal",
              "warn" if nutrition["avg_kcal_per_order"] > REF_MEAL_KCAL else ""),
        _tile("单餐平均钠", "%.0f" % nutrition["avg_sodium_per_order_mg"], " mg",
              "warn" if nutrition["avg_sodium_per_order_mg"] > REF_DAILY_SODIUM_MG * 0.35 else ""),
        _tile("饮料热量占比", "%.0f" % (nutrition["drink_energy_ratio"] * 100), " %",
              "warn" if nutrition["drink_energy_ratio"] > 0.35 else ""),
    ])
    ratios = nutrition["energy_ratios"]
    macro_bar = (
        '<i style="width:%.1f%%;background:#7A5AF8"></i>'
        '<i style="width:%.1f%%;background:#E8890C"></i>'
        '<i style="width:%.1f%%;background:#FFC72C"></i>'
        % (ratios["protein"] * 100, ratios["fat"] * 100, ratios["carb"] * 100)
    )
    macro_legend = (
        '<b><i style="background:#7A5AF8"></i>蛋白质 %.0f%%</b>'
        '<b><i style="background:#E8890C"></i>脂肪 %.0f%%</b>'
        '<b><i style="background:#FFC72C"></i>碳水 %.0f%%</b>'
        % (ratios["protein"] * 100, ratios["fat"] * 100, ratios["carb"] * 100)
    )
    sodium_ratio = nutrition["avg_sodium_per_order_mg"] / REF_DAILY_SODIUM_MG * 100
    sodium_metric = _metric(
        "单餐钠占每日上限（%d mg）" % REF_DAILY_SODIUM_MG,
        "%.0f mg ｜ %.0f%%" % (nutrition["avg_sodium_per_order_mg"], sodium_ratio),
        sodium_ratio, "#DA291C")

    # 钱包
    wallet_tiles = "".join([
        _tile("累计消费", "¥%.1f" % wallet["total_spend"]),
        _tile("客单价", "¥%.1f" % wallet["avg_ticket"]),
        _tile("月均消费", "¥%.1f" % wallet["monthly_spend"],
              "warn" if wallet["monthly_spend"] > REF_MONTHLY_BUDGET else ""),
        _tile("有效订单", "%d" % wallet["order_count"], " 单"),
    ])
    store_metric = ""
    if wallet["top_stores"]:
        top_name, top_count = wallet["top_stores"][0]["name"], wallet["top_stores"][0]["count"]
        store_metric = _metric(
            "门店集中度 · %s" % top_name,
            "%d / %d 单 ｜ %.0f%%" % (top_count, wallet["order_count"],
                                     wallet["store_concentration"] * 100),
            wallet["store_concentration"] * 100, "#E8890C")

    # 复购榜
    dish_total = sum(d["count"] for d in wallet["top_dishes"])
    max_count = max([d["count"] for d in wallet["top_dishes"]] or [1])
    rank_html = []
    for index, dish in enumerate(wallet["top_dishes"], 1):
        mark = '<span class="est">≈</span>' if dish.get("estimated") else ""
        rank_html.append(
            '<div class="rank"><div class="rank-no%s">%d</div>'
            '<div class="rank-name">%s%s</div>'
            '<div class="rank-bar"><i style="width:%.0f%%"></i></div>'
            '<div class="rank-count">×%d</div></div>'
            % (" ghost" if index > 3 else "", index, _esc(dish["name"]), mark,
               dish["count"] / max_count * 100, dish["count"])
        )
    dishes_html = "".join(rank_html)

    # 权益
    points_tiles = "".join([
        _tile("可用积分", "%g" % points["available"]),
        _tile("已过期积分", "%g" % points["expired"],
              " (%.0f%%)" % (points["expired_ratio"] * 100),
              "warn" if points["expired_ratio"] > 0.2 else "good"),
    ])
    coupon_html = []
    for coupon in metrics["coupons"]["items"]:
        price = coupon.get("price")
        price_text = ("¥%g" % price) if price else "券"
        urgent = coupon["days_left"] <= 3 and coupon["days_left"] >= 0
        tag = '<span class="tag%s">%s</span>' % (" warn" if urgent else "",
                                                 ("今天到期" if coupon["days_left"] == 0 else "剩 %d 天" % coupon["days_left"])
                                                 if urgent else "有效")
        coupon_html.append(
            '<div class="ticket"><div class="ticket-price">%s</div>'
            '<div class="ticket-body"><div class="ticket-name">%s%s</div>'
            '<div class="ticket-meta">%s 到期</div></div></div>'
            % (_esc(price_text), _esc(coupon["name"]), tag, _esc(coupon.get("expire") or "—"))
        )
    coupons_html = "".join(coupon_html)

    # 活动
    campaign_html = ""
    if metrics["campaign"]["count"]:
        items = "".join("<li>%s</li>" % _esc(t) for t in metrics["campaign"]["titles"][:5])
        campaign_html = (
            '<div class="section"><div class="sec-head"><div class="sec-title">活动日历</div>'
            '<div class="sec-note">%d 个活动</div></div><ul class="list">%s</ul></div>'
            % (metrics["campaign"]["count"], items)
        )

    # 建议
    advice_html = []
    for advice in metrics["advice"]:
        advice_html.append(
            '<div class="adv %s"><div class="adv-icon">%s</div><div><b>%s</b><p>%s</p></div></div>'
            % (advice["level"], ADVICE_ICONS.get(advice["level"], "💡"),
               _esc(advice["title"]), _esc(advice["detail"]))
        )
    advice_block = "".join(advice_html)

    # 数据可信度
    pills = "".join('<span class="pill">%s</span>' % _esc(n) for n in coverage["unknown_names"][:8])
    coverage_note = (
        "营养匹配：精确 <b>%d</b> 项 ｜ 近似 <b>%d</b> 项 ｜ 品类估算 <b>%d</b> 项 ｜ 未覆盖 <b>%d</b> 项，"
        "覆盖率 <b>%.0f%%</b>。带 ≈ 的餐品热量为品类估算值，仅供趋势参考。"
        % (coverage["exact"], coverage["approx"], coverage["estimated"], coverage["unknown"],
           coverage["known_ratio"] * 100)
    )
    if pills:
        coverage_note += "<br><br>未覆盖餐品：" + pills

    values = {
        "name": _esc(name or "匿名麦门人"),
        "time": metrics["generated_at"],
        "grade": _esc(metrics["grade"]),
        "grade_comment": _esc(grade_comment(metrics)),
        "score": ("%.1f" % metrics["score"]) if metrics["score"] is not None else "—",
        "ring": ring,
        "verdict_title": _esc(verdict_title),
        "verdict_body": _esc(verdict_body),
        "dims": dims_html,
        "meal_count": metrics["nutrition"]["meal_count"],
        "nutrition_tiles": nutrition_tiles,
        "macro_bar": macro_bar,
        "macro_legend": macro_legend,
        "sodium_metric": sodium_metric,
        "span_days": wallet["span_days"],
        "wallet_tiles": wallet_tiles,
        "store_metric": store_metric,
        "dish_total": dish_total,
        "dishes": dishes_html,
        "points_tiles": points_tiles,
        "coupons": coupons_html,
        "campaign": campaign_html,
        "advice_count": len(metrics["advice"]),
        "advice": advice_block,
        "coverage_note": coverage_note,
    }
    return _load_template().safe_substitute(values)


def grade_comment(metrics):
    dims = {k: v for k, v in metrics["dimensions"].items() if v is not None}
    if not dims:
        return "没有查到可分析的历史订单，先去下过几单再来体检。"
    weakest = min(dims, key=lambda k: dims[k])
    labels = {"nutrition": "营养均衡", "wallet": "钱包健康",
              "entitlement": "权益把控", "habit": "习惯结构"}
    return "最短板在「%s」（%.1f 分），先补这一项提升最快。" % (labels[weakest], dims[weakest])


# ---------------------------------------------------------------- 主流程
def load_raw(raw_dir):
    raw = {}
    if not os.path.isdir(raw_dir):
        return raw
    for name in os.listdir(raw_dir):
        path = os.path.join(raw_dir, name)
        if os.path.isfile(path):
            raw[name] = read_text(path)
    return raw


def pick(raw, *names):
    for name in names:
        for key in raw:
            if key == name or key.startswith(name):
                return raw[key]
    return None


def main():
    parser = argparse.ArgumentParser(description="麦门健康体检官 · 体检引擎")
    parser.add_argument("--raw-dir", required=True, help="存放 MCP 原始返回的目录")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--name", default="", help="体检人昵称")
    args = parser.parse_args()

    raw = load_raw(args.raw_dir)
    if not raw:
        raise SystemExit("raw 目录为空：%s" % args.raw_dir)

    orders = parse_orders(extract_json(pick(raw, "order-list") or ""))
    nutrition_payload = extract_json(pick(raw, "list-nutrition-foods") or "")
    nutrition_text = (nutrition_payload or {}).get("data") if nutrition_payload else None
    table = parse_nutrition(nutrition_text or "")
    category_index = build_category_index(table)

    items = collect_items(orders, table, category_index)
    account = (extract_json(pick(raw, "query-my-account") or "") or {}).get("data") or {}
    mall = extract_json(pick(raw, "mall-order-list") or "")
    lottery = (extract_json(pick(raw, "query-lottery-info") or "") or {}).get("data") or {}
    coupons_text = pick(raw, "query-my-coupons") or ""
    campaign_text = pick(raw, "campaign-calendar") or ""
    now_payload = (extract_json(pick(raw, "now-time-info") or "") or {}).get("data") or {}
    now = None
    if now_payload.get("formatted"):
        try:
            now = datetime.datetime.strptime(now_payload["formatted"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            now = None

    metrics = analyze(orders, items, account, mall, coupons_text, lottery, campaign_text, now)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(render_markdown(metrics, args.name))
    with open(os.path.join(args.out, "report.html"), "w", encoding="utf-8") as fh:
        fh.write(render_html(metrics, args.name))

    print("麦门健康分: %s" % (("%s (%s)" % (metrics["score"], metrics["grade"]))
                              if metrics["score"] is not None else "数据不足（缺少历史订单或账户数据）"))
    print("订单 %d 单 / 营养条目 %d 项 / 覆盖率 %.0f%%" % (
        metrics["wallet"]["order_count"], coverage_count(metrics), metrics["coverage"]["known_ratio"] * 100))
    print("输出目录: %s" % os.path.abspath(args.out))


def coverage_count(metrics):
    return metrics["coverage"]["items_total"]


if __name__ == "__main__":
    main()
