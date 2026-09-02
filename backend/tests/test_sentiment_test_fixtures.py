import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import routes
from models.database import Analysis, Base, Comment, SentimentResult
from services.sentiment_contract import V2_EMOTION_LABELS, V2_STYLE_LABELS
from services.sentiment_test_fixtures import FIXTURE_CASES


class SentimentTestFixtureRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.session_patch = patch.object(routes, "SessionLocal", self.sessions)
        self.enabled_patch = patch.object(routes, "TEST_FIXTURES_ENABLED", True)
        self.session_patch.start()
        self.enabled_patch.start()

    def tearDown(self):
        self.enabled_patch.stop()
        self.session_patch.stop()
        self.engine.dispose()

    def test_writes_all_fixture_comments_with_reply_relationships(self):
        response = routes.create_sentiment_test_fixture()

        self.assertEqual(response["status"], "done")
        self.assertEqual(response["mode"], "nlp")
        self.assertEqual(response["total_comments"], 24)
        self.assertEqual(len(response["fixture_cases"]), 24)

        session = self.sessions()
        try:
            analysis = session.get(Analysis, response["analysis_id"])
            comments = session.query(Comment).filter_by(analysis_id=analysis.id).all()
            result = session.query(SentimentResult).filter_by(analysis_id=analysis.id).one()
            self.assertEqual(analysis.bv, "TEST-SENTIMENT-24")
            self.assertEqual(len(comments), 24)
            self.assertEqual(sum(comment.parent_rpid is not None for comment in comments), 16)
            self.assertEqual(result.positive_count + result.negative_count + result.neutral_count, 24)
        finally:
            session.close()

    def test_catalog_exposes_v2_emotions_and_styles(self):
        response = routes.get_sentiment_test_fixture_catalog()
        expected_emotions = {case["expected_emotion"] for case in response["cases"]}
        expected_styles = {case["expected_style"] for case in response["cases"]}

        self.assertEqual(len(FIXTURE_CASES), 24)
        self.assertEqual(
            expected_emotions,
            V2_EMOTION_LABELS,
        )
        self.assertEqual(expected_styles, V2_STYLE_LABELS)

    def test_fixture_routes_are_hidden_when_disabled(self):
        with patch.object(routes, "TEST_FIXTURES_ENABLED", False):
            with self.assertRaises(HTTPException) as raised:
                routes.create_sentiment_test_fixture()

        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
