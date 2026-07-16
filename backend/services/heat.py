"""热度分析服务 —— 评论时间序列"""

from collections import Counter
from datetime import datetime, timedelta


from datetime import datetime


def analyze_heat(comments: list[dict]) -> dict:
    """分析评论热度——按时段聚合"""
    if not comments:
        return {"timeline": [], "peak_hour": None, "peak_count": 0, "hourly_distribution": []}

    # Convert post_time to datetime, handling both string and datetime inputs
    def _to_dt(ts):
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str) and ts:
            try:
                return datetime.fromisoformat(ts)
            except ValueError:
                return None
        return None

    timestamps = []
    for c in comments:
        pt = c.get("post_time")
        dt = _to_dt(pt)
        if dt:
            timestamps.append(dt)

    if not timestamps:
        return {"timeline": [], "peak_hour": None, "peak_count": 0, "hourly_distribution": []}

    # 计算时间范围
    min_time = min(timestamps)
    max_time = max(timestamps)
    span_hours = max(1, int((max_time - min_time).total_seconds() // 3600) + 1)

    # 按小时聚合
    hourly: Counter = Counter()
    for ts in timestamps:
        hour_key = ts.replace(minute=0, second=0, microsecond=0)
        hourly[hour_key] += 1

    # 生成完整时间轴
    timeline = []
    current = min_time.replace(minute=0, second=0, microsecond=0)
    end = max_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    peak_hour = None
    peak_count = 0

    while current <= end:
        cnt = hourly.get(current.replace(minute=0, second=0, microsecond=0), 0)
        timeline.append({
            "time": current.strftime("%Y-%m-%d %H:%M"),
            "count": cnt,
        })
        if cnt > peak_count:
            peak_count = cnt
            peak_hour = current.strftime("%Y-%m-%d %H:%M")
        current = current + timedelta(hours=1)

    # 按小时段（0-23）分布
    hour_dist = Counter()
    for ts in timestamps:
        hour_dist[ts.hour] += 1
    hourly_distribution = [{"hour": h, "count": hour_dist.get(h, 0)} for h in range(24)]

    return {
        "timeline": timeline,
        "peak_hour": peak_hour,
        "peak_count": peak_count,
        "hourly_distribution": hourly_distribution,
    }
