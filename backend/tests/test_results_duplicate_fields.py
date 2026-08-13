from datetime import datetime
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import routes
from models.database import Analysis, Base, Comment


class ResultDuplicateFieldTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        db = self.sessions()
        analysis = Analysis(
            bv="BV1DUPLICATE", avid=1, video_title="重复字段测试",
            status="done", mode="nlp", total_comments=4,
        )
        db.add(analysis)
        db.flush()
        db.add_all([
            Comment(
                analysis_id=analysis.id, rpid=10, content="完全重复", gender="男",
                sentiment_label="positive", post_time=datetime(2026, 8, 1, 12),
            ),
            Comment(
                analysis_id=analysis.id, rpid=20, content="完全重复", gender="女",
                sentiment_label="negative", post_time=datetime(2026, 8, 2, 12),
            ),
            Comment(
                analysis_id=analysis.id, rpid=30, content="完全重复 ",
                sentiment_label="neutral", post_time=datetime(2026, 8, 3, 12),
            ),
            Comment(
                analysis_id=analysis.id, rpid=40, content="独立评论",
                sentiment_label="neutral", post_time=datetime(2026, 8, 4, 12),
            ),
        ])
        db.commit()
        self.analysis_id = analysis.id
        db.close()
        self.session_patch = patch.object(routes, "SessionLocal", self.sessions)
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()

    def test_results_return_objective_duplicate_annotations_and_statistics(self):
        result = routes.get_results(self.analysis_id)

        by_rpid = {comment["rpid"]: comment for comment in result["comments"]}
        first, second = by_rpid[10], by_rpid[20]
        self.assertTrue(first["is_exact_duplicate"])
        self.assertTrue(second["is_exact_duplicate"])
        self.assertEqual(first["duplicate_group_size"], 2)
        self.assertEqual(first["duplicate_group_key"], second["duplicate_group_key"])
        self.assertTrue(first["is_duplicate_canonical"])
        self.assertFalse(second["is_duplicate_canonical"])
        self.assertFalse(by_rpid[30]["is_exact_duplicate"])
        self.assertIsNone(by_rpid[30]["duplicate_group_key"])
        self.assertEqual(result["duplicate_statistics"], {
            "group_count": 1,
            "involved_comments": 2,
            "duplicate_excess": 1,
            "involved_ratio": 0.5,
        })
        self.assertNotIn("水军", str(result))

    def test_filtered_keywords_are_rebuilt_from_the_final_collection(self):
        db = self.sessions()
        analysis = db.query(Analysis).filter_by(id=self.analysis_id).first()
        db.query(Comment).filter_by(analysis_id=self.analysis_id).delete()
        db.add_all([
            Comment(
                analysis_id=analysis.id,
                rpid=index + 1,
                gender="男",
                content=f"term{index:03d}",
                sentiment_label="positive",
                post_time=datetime(2026, 8, 1, 12),
            )
            for index in range(500)
        ])
        db.add(Comment(
            analysis_id=analysis.id,
            rpid=1000,
            gender="女",
            content="filteredonly",
            sentiment_label="positive",
            post_time=datetime(2026, 8, 1, 12),
        ))
        analysis.total_comments = 501
        db.commit()
        db.close()

        initial = routes.get_results(self.analysis_id)
        self.assertNotIn("filteredonly", {item["word"] for item in initial["keywords"]})

        response = routes.get_filtered_keywords(self.analysis_id, {
            "filters": {"gender": "female", "duplicateMode": "include"},
        })

        self.assertEqual(response["matched_count"], 1)
        self.assertEqual(response["keywords"], [{"word": "filteredonly", "count": 1}])

    def test_filtered_keywords_reject_invalid_filters_without_model_calls(self):
        with self.assertRaises(HTTPException) as raised:
            routes.get_filtered_keywords(self.analysis_id, {
                "filters": {"duplicateMode": "unknown"},
            })

        self.assertEqual(raised.exception.status_code, 400)

    def test_same_content_never_forms_a_duplicate_group_across_analyses(self):
        db = self.sessions()
        other_analysis = Analysis(
            bv="BV1OTHERTEST", avid=2, video_title="另一分析",
            status="done", mode="nlp", total_comments=1,
        )
        db.add(other_analysis)
        db.flush()
        db.add(Comment(
            analysis_id=other_analysis.id,
            rpid=50,
            content="跨分析相同文本",
            sentiment_label="neutral",
            post_time=datetime(2026, 8, 5, 12),
        ))
        first_analysis = Analysis(
            bv="BV1FIRSTTEST", avid=3, video_title="首个单条分析",
            status="done", mode="nlp", total_comments=1,
        )
        db.add(first_analysis)
        db.flush()
        db.add(Comment(
            analysis_id=first_analysis.id,
            rpid=60,
            content="跨分析相同文本",
            sentiment_label="neutral",
            post_time=datetime(2026, 8, 5, 13),
        ))
        db.commit()
        other_id = other_analysis.id
        first_id = first_analysis.id
        db.close()

        first_result = routes.get_results(first_id)
        other_result = routes.get_results(other_id)

        for result in (first_result, other_result):
            self.assertEqual(len(result["comments"]), 1)
            self.assertFalse(result["comments"][0]["is_exact_duplicate"])
            self.assertIsNone(result["comments"][0]["duplicate_group_key"])
            self.assertEqual(result["duplicate_statistics"]["group_count"], 0)
            self.assertEqual(result["duplicate_statistics"]["involved_comments"], 0)


if __name__ == "__main__":
    unittest.main()
