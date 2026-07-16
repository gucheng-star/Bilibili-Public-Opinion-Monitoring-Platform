"""地域分析服务 —— 基于 IP 属地"""

from collections import Counter

# 中国省份/直辖市/自治区标准名称集合
PROVINCES = {
    "北京", "天津", "上海", "重庆",
    "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东",
    "河南", "湖北", "湖南", "广东", "海南",
    "四川", "贵州", "云南", "陕西", "甘肃", "青海",
    "台湾", "内蒙古", "广西", "西藏", "宁夏", "新疆",
    "香港", "澳门",
}

# IP属地字段常见变体映射
LOCATION_ALIASES = {
    "中国": None,
    "未知": None,
    "其它": None,
}


def normalize_location(raw: str) -> str | None:
    """将 IP属地字段标准化为省份名"""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    if raw in LOCATION_ALIASES:
        return LOCATION_ALIASES[raw]
    if raw in PROVINCES:
        return raw
    # 尝试前缀匹配（如"广东"匹配到）
    for p in PROVINCES:
        if raw.startswith(p):
            return p
    # 特殊处理："中国xx" -> "xx"
    if raw.startswith("中国") and len(raw) > 2:
        suffix = raw[2:]
        if suffix in PROVINCES:
            return suffix
    return raw


def analyze_region(comments: list[dict]) -> list[dict]:
    """分析评论地域分布"""
    counter: Counter = Counter()
    for c in comments:
        loc = normalize_location(c.get("ip_location", ""))
        if loc:
            counter[loc] += 1

    total = sum(counter.values())
    return [
        {"region": r, "count": cnt, "percentage": round(cnt / total * 100, 2) if total else 0}
        for r, cnt in counter.most_common()
    ]
