#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
精简版业务 CSV 数据集生成工具
特点：
1. 精简业务表数量（从 20 张精简至 6 张核心业务分析表）
2. 精简数据量（每张表数十至数百行，易于肉眼阅读、Excel查看和测试验证）
3. 金额统一使用「万元」为单位（保留2位小数）
4. 表头全部采用清晰明确的中文列名，编码采用 UTF-8 BOM，避免乱码
5. 数据逻辑自洽，支持多样化的统计分析、趋势图、柱状图、饼图和风控审计测试
"""

import csv
import json
import random
import zipfile
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# 固定随机种子确保每次生成一致且可复现
SEED = 20261015
random.seed(SEED)

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "datasets" / "simplified_csv"
ZIP_PATH = ROOT_DIR / "datasets" / "csv.zip"


def round_wan(val: float | Decimal) -> str:
    """四舍五入保留2位小数文本"""
    d = Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(d)


# 1. 基础维度与业务字典
REGIONS = {
    "华东": {"provinces": ["上海市", "江苏省", "浙江省", "山东省", "安徽省"], "leader": "林建国", "target_2025": 14000.0, "target_2026": 16000.0},
    "华北": {"provinces": ["北京市", "河北省", "山西省", "天津市", "内蒙古自治区"], "leader": "宋志远", "target_2025": 13500.0, "target_2026": 15000.0},
    "华南": {"provinces": ["广东省", "福建省", "广西壮族自治区", "海南省"], "leader": "周海东", "target_2025": 11000.0, "target_2026": 13000.0},
    "华中": {"provinces": ["湖北省", "湖南省", "河南省", "江西省"], "leader": "陈晓明", "target_2025": 8500.0, "target_2026": 9500.0},
    "西南": {"provinces": ["四川省", "重庆市", "云南省", "贵州省"], "leader": "唐文斌", "target_2025": 8000.0, "target_2026": 9000.0},
    "西北": {"provinces": ["陕西省", "甘肃省", "青海省", "新疆维吾尔自治区"], "leader": "马金虎", "target_2025": 6500.0, "target_2026": 7500.0},
    "东北": {"provinces": ["辽宁省", "吉林省", "黑龙江省"], "leader": "赵守义", "target_2025": 5000.0, "target_2026": 5500.0},
}

INDUSTRIES = [
    "政务公共", "金融证券", "医疗卫生", "高等教育", "互联网与软件", "智能制造", "能源电力"
]

CUSTOMER_NAMES = [
    ("华东智能电网集团", "华东", "能源电力", "战略大客户"),
    ("长三角大数据计算中心", "华东", "互联网与软件", "战略大客户"),
    ("江苏紫金智能制造股份", "华东", "智能制造", "核心客户"),
    ("浙江省第一人民医院", "华东", "医疗卫生", "核心客户"),
    ("上海现代金融信息服务", "华东", "金融证券", "战略大客户"),
    ("华北政务云创新中心", "华北", "政务公共", "战略大客户"),
    ("北京信达证券股份有限公司", "华北", "金融证券", "战略大客户"),
    ("燕山工业自动化有限公司", "华北", "智能制造", "核心客户"),
    ("清华协同创新研究院", "华北", "高等教育", "核心客户"),
    ("天津海洋工程装备技术", "华北", "能源电力", "普通客户"),
    ("南方数字健康科技股份", "华南", "医疗卫生", "战略大客户"),
    ("广东先锋微电子集团", "华南", "智能制造", "战略大客户"),
    ("深圳前海开源基金", "华南", "金融证券", "核心客户"),
    ("厦门大学信息技术中心", "华南", "高等教育", "核心客户"),
    ("广西桂林电网调度中心", "华南", "能源电力", "普通客户"),
    ("华中电力自动化系统院", "华中", "能源电力", "核心客户"),
    ("武汉同济现代医疗科技", "华中", "医疗卫生", "核心客户"),
    ("湖南三湘数智装备股份", "华中", "智能制造", "核心客户"),
    ("江西智能政务公共平台", "华中", "政务公共", "普通客户"),
    ("成渝超算联合中心", "西南", "互联网与软件", "战略大客户"),
    ("四川华西数字化医院", "西南", "医疗卫生", "核心客户"),
    ("重庆长安新能源车联网", "西南", "智能制造", "战略大客户"),
    ("贵州山河大数据科技", "西南", "政务公共", "核心客户"),
    ("西安现代航空航天制造", "西北", "智能制造", "战略大客户"),
    ("西北油田数字测控工程", "西北", "能源电力", "核心客户"),
    ("兰州大学信息工程学院", "西北", "高等教育", "普通客户"),
    ("乌鲁木齐政务数字化中心", "西北", "政务公共", "核心客户"),
    ("沈阳高端数控机床集团", "东北", "智能制造", "核心客户"),
    ("吉林长白数字农业系统", "东北", "政务公共", "普通客户"),
    ("哈尔滨工业大学计算学院", "东北", "高等教育", "核心客户"),
    ("大连现代港口物流科技", "东北", "互联网与软件", "普通客户"),
]

PRODUCTS = [
    # (产品线, 产品型号, 类别, 单价_万元, 成本率)
    ("通用计算产品线", "Server-R5200-G5", "双路机架服务器", 3.20, 0.68),
    ("通用计算产品线", "Server-R5500-G5", "多路高性能服务器", 6.80, 0.65),
    ("智能计算产品线", "AI-Station-G8", "大模型推理服务器", 18.50, 0.72),
    ("智能计算产品线", "AI-Cluster-Max", "训练算力一体机", 48.00, 0.75),
    ("企业存储产品线", "Storage-KF8200", "分布式全闪存储", 22.00, 0.62),
    ("企业存储产品线", "Storage-KS3200", "混合统一存储阵列", 12.50, 0.60),
    ("政企云解决方案", "GovCloud-V3", "私有云底座平台", 35.00, 0.58),
    ("政企云解决方案", "EmgCommand-2", "应急指挥调度系统", 55.00, 0.55),
    ("网络与数据安全", "SecGate-Pro", "万兆下一代安全网关", 4.50, 0.50),
    ("网络与数据安全", "SecData-Shield", "云安全数据脱敏堡垒", 8.80, 0.52),
]

SALES_REPS = ["张伟", "李娜", "王磊", "刘敏", "陈波", "赵强", "黄丽", "杨洋", "周鹏", "吴霞"]
CHANNELS = ["直销", "核心代理商", "行业ISV合作伙伴"]


def write_csv(filename: str, rows: list[dict]):
    """写入带 BOM 的 UTF-8 CSV 文件"""
    filepath = OUTPUT_DIR / filename
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"已生成: {filename} ({len(rows)} 行, {filepath.stat().st_size / 1024:.1f} KB)")


def generate_sales_orders():
    """生成 01_销售订单明细.csv (精简约 360 条典型订单)"""
    orders = []
    # 2025年 12个月 + 2026年 1-9月，共21个月
    months = [f"{y}-{m:02d}" for y in [2025] for m in range(1, 13)] + [f"{2026}-{m:02d}" for m in range(1, 10)]

    order_seq = 1
    for m in months:
        y, month_num = int(m.split("-")[0]), int(m.split("-")[1])
        # 每月产生 15~20 个订单
        orders_in_month = 16 if month_num in [3, 6, 9, 12] else 14
        if y == 2026:
            orders_in_month += 2

        for _ in range(orders_in_month):
            order_id = f"SO{y}{month_num:02d}{order_seq:04d}"
            order_seq += 1

            day = random.randint(1, 28)
            order_date = f"{m}-{day:02d}"

            cust_name, region, industry, cust_tier = random.choice(CUSTOMER_NAMES)
            province = random.choice(REGIONS[region]["provinces"])
            prod_line, prod_model, category, base_price, cost_rate = random.choice(PRODUCTS)
            channel = random.choice(CHANNELS)
            rep = random.choice(SALES_REPS)

            # 销售数量
            if cust_tier == "战略大客户":
                qty = random.choice([3, 5, 8, 10, 15])
            elif cust_tier == "核心客户":
                qty = random.choice([2, 3, 5, 6])
            else:
                qty = random.choice([1, 2, 3])

            # 折扣与价格 (万元)
            discount = random.choice([0.85, 0.88, 0.90, 0.92, 0.95, 1.00])
            unit_price = round(base_price * discount, 2)
            order_amount = round(unit_price * qty, 2)

            # 订单状态 (92% 已完成，5% 已取消，3% 已退货)
            status_rand = random.random()
            if status_rand < 0.92:
                status = "已完成"
                revenue = order_amount
                refund_amount = 0.0
                cost = round(revenue * cost_rate, 2)
                profit = round(revenue - cost, 2)
                margin = round((profit / revenue * 100), 2) if revenue > 0 else 0.0
            elif status_rand < 0.97:
                status = "已取消"
                revenue = 0.0
                refund_amount = 0.0
                cost = 0.0
                profit = 0.0
                margin = 0.0
            else:
                status = "已退货"
                revenue = 0.0
                refund_amount = order_amount
                cost = 0.0
                profit = 0.0
                margin = 0.0

            orders.append({
                "订单编号": order_id,
                "下单日期": order_date,
                "年月": m,
                "年份": y,
                "所属大区": region,
                "省份": province,
                "所属行业": industry,
                "客户名称": cust_name,
                "客户级别": cust_tier,
                "产品线": prod_line,
                "产品型号": prod_model,
                "产品类别": category,
                "销售渠道": channel,
                "销售数量": qty,
                "单价(万元)": round_wan(unit_price),
                "订单金额(万元)": round_wan(order_amount),
                "订单状态": status,
                "确认收入(万元)": round_wan(revenue),
                "销售成本(万元)": round_wan(cost),
                "毛利润(万元)": round_wan(profit),
                "毛利率(%)": round_wan(margin),
                "退款金额(万元)": round_wan(refund_amount),
                "销售负责人": rep,
            })

    return orders


def generate_receivables(orders):
    """生成 02_客户应收与回款.csv (挑选约 100 笔已完成的代表性发票/应收)"""
    receivables = []
    completed_orders = [o for o in orders if o["订单状态"] == "已完成"]
    # 挑选其中 100 笔
    selected_orders = completed_orders[::max(1, len(completed_orders) // 100)][:100]

    as_of = date(2026, 10, 1)
    rec_seq = 1

    for o in selected_orders:
        inv_id = f"INV{o['年份']}{rec_seq:04d}"
        rec_seq += 1

        order_d = date.fromisoformat(o["下单日期"])
        inv_date = order_d + timedelta(days=random.randint(1, 10))
        # 账期通常为 30天、60天或90天
        term_days = random.choice([30, 45, 60, 90])
        due_date = inv_date + timedelta(days=term_days)

        amount = float(o["确认收入(万元)"])

        # 根据到期日与基准日计算回款状态
        if due_date < as_of:
            # 已经到期
            overdue_days = (as_of - due_date).days
            # 模拟不同回款比例
            r = random.random()
            if r < 0.70:
                # 已完全结清
                paid = amount
                balance = 0.0
                status = "已结清"
                bucket = "正常结清"
                risk = "低风险"
                overdue = 0
            elif r < 0.88:
                # 部分回款
                paid = round(amount * random.choice([0.4, 0.6, 0.8]), 2)
                balance = round(amount - paid, 2)
                status = "部分回款"
                overdue = overdue_days
                if overdue <= 30:
                    bucket = "逾期1-30天"
                    risk = "低风险"
                elif overdue <= 90:
                    bucket = "逾期31-90天"
                    risk = "中风险"
                else:
                    bucket = "逾期90天以上"
                    risk = "高风险"
            else:
                # 逾期未付
                paid = 0.0
                balance = amount
                status = "未回款"
                overdue = overdue_days
                if overdue <= 30:
                    bucket = "逾期1-30天"
                    risk = "中风险"
                elif overdue <= 90:
                    bucket = "逾期31-90天"
                    risk = "高风险"
                else:
                    bucket = "逾期90天以上"
                    risk = "高风险"
        else:
            # 尚未到期
            overdue = 0
            r = random.random()
            if r < 0.3:
                paid = amount
                balance = 0.0
                status = "已结清"
                bucket = "正常期内"
                risk = "低风险"
            else:
                paid = 0.0
                balance = amount
                status = "未到期"
                bucket = "正常期内"
                risk = "低风险"

        receivables.append({
            "账单编号": inv_id,
            "关联订单号": o["订单编号"],
            "客户名称": o["客户名称"],
            "所属行业": o["所属行业"],
            "所属大区": o["所属大区"],
            "销售负责人": o["销售负责人"],
            "开票日期": str(inv_date),
            "到期付款日": str(due_date),
            "开票金额(万元)": round_wan(amount),
            "已回款金额(万元)": round_wan(paid),
            "欠款余额(万元)": round_wan(balance),
            "逾期天数": overdue,
            "账龄区间": bucket,
            "回款状态": status,
            "催收风险等级": risk,
        })

    return receivables


def generate_monthly_summary(orders):
    """生成 03_月度经营与销售汇总.csv (按年月 + 大区聚合，非常适合做月度折线图与指标对比)"""
    agg = {}
    for o in orders:
        if o["订单状态"] != "已完成":
            continue
        key = (o["年月"], o["所属大区"])
        if key not in agg:
            agg[key] = {
                "order_cnt": 0,
                "qty": 0,
                "revenue": 0.0,
                "cost": 0.0,
                "profit": 0.0,
            }
        agg[key]["order_cnt"] += 1
        agg[key]["qty"] += int(o["销售数量"])
        agg[key]["revenue"] += float(o["确认收入(万元)"])
        agg[key]["cost"] += float(o["销售成本(万元)"])
        agg[key]["profit"] += float(o["毛利润(万元)"])

    summary = []
    # 按照年月排序
    for (ym, region) in sorted(agg.keys()):
        data = agg[(ym, region)]
        rev = round(data["revenue"], 2)
        cost = round(data["cost"], 2)
        profit = round(data["profit"], 2)
        margin = round(profit / rev * 100, 2) if rev > 0 else 0.0

        # 月度目标：按大区基准月均目标浮动 ±15%
        y = int(ym.split("-")[0])
        annual_target = REGIONS[region][f"target_2025" if y == 2025 else "target_2026"]
        base_monthly = annual_target / 12.0
        # 简化设一个合理的目标
        monthly_target = round(base_monthly * random.uniform(0.85, 1.10) / 10, 2) * 10  # 适当缩放匹配样本量
        # 为使分析具有真实性，让目标和收入在同数量级
        target = round(rev * random.uniform(0.9, 1.15), 2)
        rate = round(rev / target * 100, 2) if target > 0 else 100.0

        summary.append({
            "年月": ym,
            "所属大区": region,
            "大区负责人": REGIONS[region]["leader"],
            "完成订单数": data["order_cnt"],
            "销售台数": data["qty"],
            "营业收入(万元)": round_wan(rev),
            "营业成本(万元)": round_wan(cost),
            "毛利润(万元)": round_wan(profit),
            "综合毛利率(%)": round_wan(margin),
            "月度目标(万元)": round_wan(target),
            "目标达成率(%)": round_wan(rate),
        })

    return summary


def generate_regional_targets():
    """生成 04_各大区经营目标达成.csv (7个大区 × 2年 = 14行，高层战略看板)"""
    rows = []
    for year in [2025, 2026]:
        # 排序便于看排名
        region_list = list(REGIONS.keys())
        # 计算 2025 和 2026 年实际
        for reg in region_list:
            info = REGIONS[reg]
            target = info["target_2025"] if year == 2025 else info["target_2026"]
            # 2025 达成率在 95%~112% 之间
            # 2026 是前9个月，按 9 个月目标（目标*0.75）或全年度预期
            if year == 2025:
                achieve_rate = round(random.uniform(96.5, 108.5), 2)
                actual = round(target * achieve_rate / 100.0, 2)
                yoy = round(random.uniform(12.0, 25.0), 2)
            else:
                # 2026 截至三季度完成情况
                achieve_rate = round(random.uniform(74.0, 85.0), 2) # 前三季度进度约75%
                actual = round(target * achieve_rate / 100.0, 2)
                yoy = round(random.uniform(8.0, 18.0), 2)

            gap = round(actual - target, 2)
            cust_count = random.randint(45, 95)
            big_deals = random.randint(8, 26)

            rows.append({
                "年份": year,
                "所属大区": reg,
                "大区负责人": info["leader"],
                "年度业绩目标(万元)": round_wan(target),
                "实际完成金额(万元)": round_wan(actual),
                "差额(万元)": round_wan(gap),
                "达成进度(%)": round_wan(achieve_rate),
                "同比增速(%)": round_wan(yoy),
                "成交客户数": cust_count,
                "重大项目数": big_deals,
            })

    # 计算排名
    for y in [2025, 2026]:
        sub = [r for r in rows if r["年份"] == y]
        sub.sort(key=lambda x: float(x["实际完成金额(万元)"]), reverse=True)
        for rank, item in enumerate(sub, 1):
            item["大区排名"] = rank

    return rows


def generate_crm_opportunities():
    """生成 05_CRM销售商机漏斗.csv (约 80 条代表性商机)"""
    stages = [
        ("初步洽谈", 10),
        ("方案交流", 30),
        ("商务谈判", 60),
        ("招投标阶段", 80),
        ("已赢单", 100),
        ("已丢单", 0),
    ]

    opp_titles = [
        "智算中心算力扩容采购项目", "新一代全闪分布式存储升级", "政务信创云底座建设工程",
        "智慧医院数字化基础设施平台", "高并发金融业务服务器集群", "工业物联网边缘计算节点",
        "超算中心智能调度系统升级", "电力数字化调度监控大屏平台", "数据中心万兆网络安全改造",
        "智能制造生产线质检算力系统"
    ]

    rows = []
    start_date = date(2026, 1, 1)

    for i in range(1, 81):
        opp_id = f"OPP2026{i:04d}"
        cust_name, region, industry, cust_tier = random.choice(CUSTOMER_NAMES)
        title = f"{cust_name[:4]}-{random.choice(opp_titles)}"
        stage_name, win_prob = random.choice(stages)

        create_d = start_date + timedelta(days=random.randint(1, 240))
        close_d = create_d + timedelta(days=random.randint(30, 90))

        # 预计金额 (万元)
        if "集群" in title or "算力" in title or "中心" in title:
            est_amount = round(random.uniform(80.0, 600.0), 2)
        else:
            est_amount = round(random.uniform(20.0, 150.0), 2)

        weighted_amount = round(est_amount * win_prob / 100.0, 2)
        rep = random.choice(SALES_REPS)

        if stage_name == "已赢单":
            status = "赢单关闭"
        elif stage_name == "已丢单":
            status = "丢单关闭"
        else:
            status = "跟进中"

        rows.append({
            "商机编号": opp_id,
            "商机名称": title,
            "客户名称": cust_name,
            "所属行业": industry,
            "所属大区": region,
            "销售负责人": rep,
            "商机阶段": stage_name,
            "赢单概率(%)": win_prob,
            "预计签约金额(万元)": round_wan(est_amount),
            "加权预期金额(万元)": round_wan(weighted_amount),
            "创建日期": str(create_d),
            "预计签约日期": str(close_d),
            "商机状态": status,
        })

    return rows


def generate_project_risks():
    """生成 06_重点项目交付与风险.csv (约 40 个重点交付项目)"""
    rows = []
    pms = ["陈工", "李经理", "孙工", "刘总监", "王经理", "周工程师"]
    risk_reasons = [
        "客户需求变更频繁，设计重构",
        "关键定制算力板卡到货延期",
        "客户机房现场土建与电力延期交付",
        "客户内部财务审批流程繁琐，款项拨付滞后",
        "第三方软件接口联调不兼容",
        "无风险，正常推进中",
    ]

    for i in range(1, 41):
        proj_id = f"PRJ2025{i:03d}"
        cust_name, region, industry, cust_tier = random.choice(CUSTOMER_NAMES)
        proj_name = f"{cust_name[:6]}信息系统工程({i}期)"

        contract_amount = round(random.uniform(150.0, 1200.0), 2)
        rec_ratio = random.choice([0.3, 0.5, 0.7, 0.9, 1.0])
        recognized_rev = round(contract_amount * rec_ratio, 2)
        collected = round(recognized_rev * random.choice([0.4, 0.7, 0.9, 1.0]), 2)
        uncollected = round(recognized_rev - collected, 2)

        plan_delivery = date(2026, random.randint(3, 9), random.randint(1, 28))
        delay = random.choice([0, 0, 0, 10, 25, 45, 75, 110])
        actual_delivery = plan_delivery + timedelta(days=delay)

        if delay == 0 and uncollected < 50:
            risk_level = "正常"
            reason = "无风险，按期交付且回款健康"
        elif delay <= 30 and uncollected < 150:
            risk_level = "低风险"
            reason = "轻微延期或尾款正常结算中"
        elif delay <= 60 or uncollected >= 200:
            risk_level = "中风险"
            reason = random.choice([r for r in risk_reasons if r != "无风险，正常推进中"])
        else:
            risk_level = "高风险"
            reason = random.choice([
                "客户需求变更频繁，交付延期超60天",
                "核心硬件停产替换导致整体工期严重滞后",
                "客户资金紧张，款项已逾期超过180天",
            ])

        rows.append({
            "项目编号": proj_id,
            "项目名称": proj_name,
            "客户名称": cust_name,
            "所属行业": industry,
            "所属大区": region,
            "项目经理": random.choice(pms),
            "合同总金额(万元)": round_wan(contract_amount),
            "已确认收入(万元)": round_wan(recognized_rev),
            "已回款金额(万元)": round_wan(collected),
            "未回款敞口(万元)": round_wan(uncollected),
            "计划交付日期": str(plan_delivery),
            "预计完成日期": str(actual_delivery),
            "延期天数": delay,
            "风险等级": risk_level,
            "主要风险诱因": reason,
        })

    return rows


def generate_readme(file_stats):
    """生成详细说明文档 README.md"""
    readme_content = f"""# 精简业务数据集 (Simplified Business CSV Dataset)

本数据集是针对原庞杂业务数据进行**全面精简、重构与标准化**后的精选业务分析套件。专为**人工分析、Excel审阅、业务报表验证与 BI/LLM 智能问答测试**而设计。

## 核心设计与精简优势

1. **中文直观表头**：所有列名采用清晰明了的中文（如 `所属大区`、`客户名称`、`订单金额(万元)`），杜绝生僻英文字段代码，便于人工秒懂与直接提问。
2. **统一金额单位**：所有金额字段统一以**「万元」**为单位，保留两位小数，告别过去动辄几千万、上亿元长串“元”数字带来的肉眼辨识疲劳，便于心算与快速核验。
3. **精简表种类与数据量**：从原先复杂的 20 张关联表精简合并为 **6 张典型业务主题表**；数据量从数十万行压缩至几十到几百行，文件总体积不足 100 KB，秒级加载，计算结果一目了然。
4. **编码规范标准**：采用 `UTF-8 with BOM (utf-8-sig)` 编码，Windows/Mac 打开 Excel、WPS 绝不出现乱码。
5. **业务逻辑严密自洽**：
   - `01_销售订单明细`：单价 × 数量 = 订单金额，收入 - 成本 = 毛利润；
   - `02_客户应收与回款`：开票金额 = 已回款金额 + 欠款余额；
   - `03_月度经营与销售汇总`：月度维度订单、收入、成本、毛利与达成率；
   - `04_各大区经营目标达成`：各大区 2025 及 2026 年业绩指标与达成排名；
   - `05_CRM销售商机漏斗`：商机阶段、赢单率与预期加权金额；
   - `06_重点项目交付与风险`：重大交付合同额、已收款、未结敞口及延期风控。

---

## 包含文件清单

| 文件名 | 行数 | 文件大小 | 业务分析场景与用途 |
| :--- | :---: | :---: | :--- |
"""
    for stat in file_stats:
        readme_content += f"| **{stat['name']}** | {stat['rows']} 行 | {stat['size_kb']:.1f} KB | {stat['desc']} |\n"

    readme_content += """
---

## 常用测试问题与 SQL 示例

在 BI 或数据分析平台中，针对上述 CSV 即可执行以下高频测试：

### 1. 销售趋势分析（折线图）
- **数据源**：`03_月度经营与销售汇总.csv`
- **问题**：按月份展示 2025 年至 2026 年全国营业收入和毛利润的变化趋势。
- **参考 SQL**：
```sql
SELECT 年月, SUM("营业收入(万元)") AS 营业收入_万元, SUM("毛利润(万元)") AS 毛利润_万元
FROM dataset
GROUP BY 年月
ORDER BY 年月;
```

### 2. 大区收入贡献排行（柱状图 / 饼图）
- **数据源**：`04_各大区经营目标达成.csv`
- **问题**：比较 2025 年各大区实际完成金额，并按金额从高到低排序。
- **参考 SQL**：
```sql
SELECT 所属大区, "实际完成金额(万元)"
FROM dataset
WHERE 年份 = 2025
ORDER BY "实际完成金额(万元)" DESC;
```

### 3. 高风险逾期欠款排查（风控列表）
- **数据源**：`02_客户应收与回款.csv`
- **问题**：筛选出催收风险等级为“高风险”的客户、欠款余额及逾期天数。
- **参考 SQL**：
```sql
SELECT 客户名称, 所属行业, "欠款余额(万元)", 逾期天数, 账龄区间
FROM dataset
WHERE 催收风险等级 = '高风险'
ORDER BY "欠款余额(万元)" DESC;
```

### 4. 重点产品销售结构（柱状图）
- **数据源**：`01_销售订单明细.csv`
- **问题**：统计各产品线的总销售收入与订单数量。
- **参考 SQL**：
```sql
SELECT 产品线, SUM("确认收入(万元)") AS 总收入_万元, COUNT(*) AS 订单数
FROM dataset
WHERE 订单状态 = '已完成'
GROUP BY 产品线
ORDER BY 总收入_万元 DESC;
```

### 5. 销售漏斗与阶段加权（漏斗图）
- **数据源**：`05_CRM销售商机漏斗.csv`
- **问题**：统计各个商机阶段的商机总数及预计签约金额。
- **参考 SQL**：
```sql
SELECT 商机阶段, COUNT(*) AS 商机数, SUM("预计签约金额(万元)") AS 预计金额_万元
FROM dataset
GROUP BY 商机阶段
ORDER BY 预计金额_万元 DESC;
```
"""
    readme_path = OUTPUT_DIR / "README.md"
    readme_path.write_text(readme_content, encoding="utf-8")
    print(f"已生成说明文档: {readme_path}")


def package_zip():
    """将 simplified_csv 目录打包成 csv.zip"""
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(OUTPUT_DIR.glob("*")):
            if p.is_file():
                zf.write(p, arcname=p.name)
    print(f"\n成功创建压缩包: {ZIP_PATH} ({ZIP_PATH.stat().st_size / 1024:.1f} KB)")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"正在生成精简版业务 CSV 数据至: {OUTPUT_DIR}")

    # 1. 销售订单明细
    orders = generate_sales_orders()
    write_csv("01_销售订单明细.csv", orders)

    # 2. 客户应收与回款
    receivables = generate_receivables(orders)
    write_csv("02_客户应收与回款.csv", receivables)

    # 3. 月度经营与销售汇总
    monthly = generate_monthly_summary(orders)
    write_csv("03_月度经营与销售汇总.csv", monthly)

    # 4. 各大区经营目标达成
    regional = generate_regional_targets()
    write_csv("04_各大区经营目标达成.csv", regional)

    # 5. CRM销售商机漏斗
    crm = generate_crm_opportunities()
    write_csv("05_CRM销售商机漏斗.csv", crm)

    # 6. 重点项目交付与风险
    projects = generate_project_risks()
    write_csv("06_重点项目交付与风险.csv", projects)

    file_stats = [
        {"name": "01_销售订单明细.csv", "rows": len(orders), "size_kb": (OUTPUT_DIR / "01_销售订单明细.csv").stat().st_size / 1024, "desc": "明细交易流水，支持大区/行业/产品线/客户/毛利等多维分析"},
        {"name": "02_客户应收与回款.csv", "rows": len(receivables), "size_kb": (OUTPUT_DIR / "02_客户应收与回款.csv").stat().st_size / 1024, "desc": "财务账期、回款进度、账龄区间与逾期欠款风控"},
        {"name": "03_月度经营与销售汇总.csv", "rows": len(monthly), "size_kb": (OUTPUT_DIR / "03_月度经营与销售汇总.csv").stat().st_size / 1024, "desc": "月度营收、成本、毛利与达成趋势，折线图首选"},
        {"name": "04_各大区经营目标达成.csv", "rows": len(regional), "size_kb": (OUTPUT_DIR / "04_各大区经营目标达成.csv").stat().st_size / 1024, "desc": "高层大区业绩看板、年度目标达成率与增长排名"},
        {"name": "05_CRM销售商机漏斗.csv", "rows": len(crm), "size_kb": (OUTPUT_DIR / "05_CRM销售商机漏斗.csv").stat().st_size / 1024, "desc": "销售前向机会、商机阶段漏斗、预测签约金额与赢单率"},
        {"name": "06_重点项目交付与风险.csv", "rows": len(projects), "size_kb": (OUTPUT_DIR / "06_重点项目交付与风险.csv").stat().st_size / 1024, "desc": "项目交付进度、延期天数、未结款敞口与风险诱因监控"},
    ]

    generate_readme(file_stats)
    package_zip()
    print("全部精简数据集与压缩包处理完成！")


if __name__ == "__main__":
    main()
