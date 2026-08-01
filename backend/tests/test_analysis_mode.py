import unittest
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import routes
from models.database import Analysis, Base


class InitialAnalysisModeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    async def test_new_analysis_forces_nlp_when_client_requests_llm(self):
        background_tasks = BackgroundTasks()
        video_info = {
            "avid": 123,
            "title": "test video",
            "cover": "https://example.com/cover.jpg",
            "play": 456,
        }

        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(routes, "get_video_info", new=AsyncMock(return_value=video_info)),
        ):
            response = await routes.start_analysis(
                {
                    "bv": "BV1TEST00000",
                    "max_comments": 20,
                    "request_delay": 1,
                    "mode": "llm",
                },
                background_tasks,
            )

        session = self.sessions()
        try:
            analysis = session.get(Analysis, response["analysis_id"])
            self.assertIsNotNone(analysis)
            self.assertEqual(analysis.mode, "nlp")
        finally:
            session.close()

        self.assertEqual(response["mode"], "nlp")
        self.assertEqual(len(background_tasks.tasks), 1)
        self.assertEqual(background_tasks.tasks[0].kwargs["mode"], "nlp")

    async def test_failed_llm_reanalysis_preserves_nlp_result(self):
        session = self.sessions()
        analysis = Analysis(
            bv="BV1TEST00000",
            avid=123,
            video_title="test video",
            status="analyzing",
            mode="nlp",
            total_comments=20,
        )
        session.add(analysis)
        session.commit()
        analysis_id = analysis.id
        session.close()

        with (
            patch.object(routes, "SessionLocal", self.sessions),
            patch.object(
                routes,
                "batch_analyze_llm",
                new=AsyncMock(side_effect=RuntimeError("model returned empty content")),
            ),
        ):
            await routes._run_reanalyze(analysis_id, [], {})

        session = self.sessions()
        try:
            preserved = session.get(Analysis, analysis_id)
            self.assertEqual(preserved.status, "done")
            self.assertEqual(preserved.mode, "nlp")
            self.assertIn("empty content", preserved.error_msg)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
