"""Create deterministic, non-production data for README screenshots.

The script only writes to the explicitly selected local data directory.  It is
intended for ``tmp/readme-screenshots-data`` and never calls Bilibili or a
model provider.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_DATA_DIR = PROJECT_ROOT / "tmp" / "readme-screenshots-data"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 README 截图用脱敏演示数据")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="SQLite 数据目录（默认：tmp/readme-screenshots-data）",
    )
    return parser.parse_args()


def _comments(analysis_id: int, start_rpid: int, count: int, day_offset: int) -> list[object]:
    from models.database import Comment

    labels = ("positive", "neutral", "negative")
    genders = ("男", "女", "保密")
    regions = ("广东", "上海", "北京", "江苏", "四川", "浙江", "湖北", "福建")
    topics = (
        "信息表达清晰，讨论重点容易理解。",
        "希望后续补充数据来源和具体案例。",
        "不同观点值得保留，方便继续核对。",
        "整体节奏合适，评论区讨论比较集中。",
        "建议把关键结论和原始证据一起查看。",
        "这是一条用于界面展示的脱敏示例评论。",
    )
    base_time = datetime(2026, 9, 1, 8, 0, 0) + timedelta(days=day_offset)
    rows: list[object] = []
    for index in range(count):
        label = labels[index % len(labels)]
        rows.append(Comment(
            analysis_id=analysis_id,
            rpid=start_rpid + index,
            root_rpid=start_rpid + index,
            username=f"示例用户{index % 18 + 1:02d}",
            gender=genders[index % len(genders)],
            ip_location=regions[index % len(regions)],
            content=topics[index % len(topics)],
            likes=(index * 7) % 86,
            sentiment_label=label,
            sentiment_score={"positive": 0.84, "neutral": 0.51, "negative": 0.79}[label],
            post_time=base_time + timedelta(minutes=index * 37),
        ))
    return rows


def main() -> None:
    args = _parse_args()
    data_dir = args.data_dir.resolve()
    if data_dir != DEFAULT_DATA_DIR.resolve():
        raise SystemExit("为避免误写其他数据目录，--data-dir 仅允许 tmp/readme-screenshots-data")

    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["BILI_DATA_DIR"] = str(data_dir)
    sys.path.insert(0, str(BACKEND_ROOT))

    from models.database import (
        AISummary,
        Analysis,
        AnalysisGroup,
        AnalysisGroupItem,
        AnalysisGroupSummary,
        Comment,
        DanmakuAnalysis,
        DanmakuSample,
        SentimentResult,
        SessionLocal,
        init_db,
    )
    from services.secure_store import protect

    init_db()
    db = SessionLocal()
    try:
        for model in (
            AnalysisGroupSummary,
            AnalysisGroupItem,
            AISummary,
            DanmakuSample,
            DanmakuAnalysis,
            SentimentResult,
            Comment,
            AnalysisGroup,
            Analysis,
        ):
            db.query(model).delete(synchronize_session=False)

        primary = Analysis(
            bv="BV1README001",
            avid=10001,
            video_title="示例：社区讨论热度观察（脱敏）",
            video_play=284_000,
            status="done",
            mode="nlp",
            total_comments=120,
            processed_comments=120,
            comment_target_count=120,
            comment_fetched_count=120,
            comment_request_delay=2.0,
            comment_collection_status="completed",
        )
        secondary = Analysis(
            bv="BV1README002",
            avid=10002,
            video_title="示例：产品体验讨论（脱敏）",
            video_play=156_000,
            status="done",
            mode="nlp",
            total_comments=48,
            processed_comments=48,
            comment_target_count=48,
            comment_fetched_count=48,
            comment_request_delay=2.0,
            comment_collection_status="completed",
        )
        tertiary = Analysis(
            bv="BV1README003",
            avid=10003,
            video_title="示例：政策话题观察（脱敏）",
            video_play=93_000,
            status="done",
            mode="nlp",
            total_comments=42,
            processed_comments=42,
            comment_target_count=42,
            comment_fetched_count=42,
            comment_request_delay=2.0,
            comment_collection_status="completed",
        )
        db.add_all((primary, secondary, tertiary))
        db.flush()

        db.add_all(_comments(primary.id, 10_000, 120, 0))
        db.add_all(_comments(secondary.id, 20_000, 48, 1))
        db.add_all(_comments(tertiary.id, 30_000, 42, 2))
        db.add_all((
            SentimentResult(analysis_id=primary.id, positive_count=40, neutral_count=40, negative_count=40),
            SentimentResult(analysis_id=secondary.id, positive_count=16, neutral_count=16, negative_count=16),
            SentimentResult(analysis_id=tertiary.id, positive_count=14, neutral_count=14, negative_count=14),
        ))

        group = AnalysisGroup(
            name="示例事件：多视频讨论对比（脱敏）",
            description="仅用于 README 界面展示的本地模拟数据。",
        )
        db.add(group)
        db.flush()
        db.add_all((
            AnalysisGroupItem(group_id=group.id, analysis_id=primary.id, position=0),
            AnalysisGroupItem(group_id=group.id, analysis_id=secondary.id, position=1),
            AnalysisGroupItem(group_id=group.id, analysis_id=tertiary.id, position=2),
        ))

        task = DanmakuAnalysis(
            analysis_id=primary.id,
            bv=primary.bv,
            avid=primary.avid,
            cid=90001,
            part_index=1,
            attempt_index=1,
            part_title="主视频（示例）",
            video_duration_seconds=720,
            status="done",
            sample_limit=60,
            request_delay=2.0,
            segment_count=2,
            requested_segments=2,
            requested_segment_indexes="[0, 1]",
            successful_segments=2,
            kept_count=60,
            ignored_count=0,
            failed_segment_indexes="[]",
        )
        db.add(task)
        db.flush()
        danmaku_labels = ("positive", "neutral", "negative")
        db.add_all(
            DanmakuSample(
                danmaku_analysis_id=task.id,
                content=f"脱敏示例弹幕 {index + 1}",
                progress_ms=index * 12_000,
                segment_index=0 if index < 30 else 1,
                sentiment_label=danmaku_labels[index % len(danmaku_labels)],
                sentiment_score=(0.82, 0.5, 0.78)[index % len(danmaku_labels)],
            )
            for index in range(60)
        )
        db.commit()
        demo_auth_path = data_dir / "readme-demo-auth.json"
        demo_auth_path.write_text(json.dumps({
            "cookie": protect("readme-demo-local-only"),
            "accounts": [{
                "cookie": protect("readme-demo-local-only"),
                "name": "README 脱敏演示",
            }],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已生成 README 脱敏演示数据：{data_dir / 'data.db'}")
        print(f"已生成本机演示凭据：{demo_auth_path}")
        print(f"单视频={primary.id}，事件={group.id}，弹幕任务={task.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
