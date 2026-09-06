import unittest
from unittest.mock import AsyncMock, patch

from api import routes
from services.bilibili import fetch_comments, get_video_info
from services.comment_collection import (
    COMMENT_COLLECTION_COMPLETED,
    COMMENT_COLLECTION_FAILED,
    COMMENT_COLLECTION_PARTIAL,
)


def make_reply(rpid: int, root: int = 0, parent: int = 0):
    return {
        "rpid": rpid,
        "root": root,
        "parent": parent,
        "ctime": 1_700_000_000 + rpid,
        "member": {"uname": f"user-{rpid}", "sex": "保密"},
        "reply_control": {"location": "IP属地：广东"},
        "content": {"message": f"comment-{rpid}"},
        "like": rpid,
    }


class FakeResponse:
    status_code = 200

    def __init__(self, replies):
        self._replies = replies

    def json(self):
        return {"code": 0, "data": {"replies": self._replies}}


class FakeClient:
    def __init__(self, pages):
        self._pages = iter(pages)

    async def get(self, *_args, **_kwargs):
        return FakeResponse(next(self._pages))


class VideoInfoClient:
    async def get(self, *_args, **_kwargs):
        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "code": 0,
                    "data": {
                        "aid": 123,
                        "title": "测试视频",
                        "duration": 660,
                        "pic": "http://example.com/cover.jpg",
                        "stat": {"view": 9, "reply": 2},
                        "pages": [
                            {"page": 1, "cid": 456, "part": "上", "duration": 600},
                            {"page": 2, "cid": 789, "part": "下", "duration": 60},
                        ],
                    },
                }
        return Response()


class BilibiliProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_info_exposes_selected_part_cid_and_duration_for_danmaku_only(self):
        info = await get_video_info(VideoInfoClient(), "BV1TEST00000")
        self.assertEqual(info["duration"], 660)
        self.assertEqual(info["pages"], [
            {"page": 1, "cid": 456, "part": "上", "duration": 600},
            {"page": 2, "cid": 789, "part": "下", "duration": 60},
        ])
        self.assertEqual(info["comment_count"], 2)

    async def test_public_video_info_exposes_real_parts_without_cid(self):
        internal = await get_video_info(VideoInfoClient(), "BV1TEST00000")

        public = routes._public_video_info(internal)

        self.assertEqual(public["pages"], [
            {"page": 1, "part": "上", "duration": 600},
            {"page": 2, "part": "下", "duration": 60},
        ])
        self.assertNotIn("cid", str(public))

    async def test_reports_real_comment_count_after_each_page(self):
        client = FakeClient([
            [make_reply(1), make_reply(2)],
            [make_reply(3), make_reply(4)],
        ])
        progress = []

        with patch("services.bilibili.asyncio.sleep", new=AsyncMock()), \
                patch("services.bilibili.random.uniform", return_value=0):
            comments = await fetch_comments(
                client,
                avid=123,
                max_comments=3,
                delay=0,
                progress_callback=progress.append,
            )

        self.assertEqual([comment["rpid"] for comment in comments], [1, 2, 3])
        self.assertEqual(progress, [2, 3])
        self.assertEqual(comments.collection_status, COMMENT_COLLECTION_COMPLETED)
        self.assertEqual(comments.target_count, 3)
        self.assertEqual(comments.fetched_count, 3)
        self.assertIsNone(comments.error_summary)

    async def test_keeps_partial_result_and_uses_safe_error_summary(self):
        class ErrorClient:
            def __init__(self):
                self.calls = 0

            async def get(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponse([make_reply(1)])
                raise RuntimeError("Cookie: SESSDATA=private-api-key")

        with patch("services.bilibili.asyncio.sleep", new=AsyncMock()), patch("services.bilibili.random.uniform", return_value=0):
            result = await fetch_comments(ErrorClient(), avid=123, max_comments=3, delay=0)

        self.assertEqual(result.collection_status, COMMENT_COLLECTION_PARTIAL)
        self.assertEqual(result.termination_reason, "request_failed")
        self.assertEqual(result.fetched_count, 1)
        self.assertNotIn("SESSDATA", result.error_summary)
        self.assertNotIn("private-api-key", result.error_summary)

    async def test_first_page_failure_has_retryable_safe_summary(self):
        class ErrorClient:
            async def get(self, *_args, **_kwargs):
                raise RuntimeError("Authorization: Bearer secret")

        result = await fetch_comments(ErrorClient(), avid=123, max_comments=3, delay=0)

        self.assertEqual(result.collection_status, COMMENT_COLLECTION_FAILED)
        self.assertEqual(result.fetched_count, 0)
        self.assertEqual(result.error_summary, "评论获取失败，可重新采集")

    async def test_source_exhaustion_before_target_is_partial_not_complete(self):
        with patch("services.bilibili.asyncio.sleep", new=AsyncMock()), patch("services.bilibili.random.uniform", return_value=0):
            result = await fetch_comments(FakeClient([[make_reply(1)], []]), avid=123, max_comments=3, delay=0)

        self.assertEqual(result.collection_status, COMMENT_COLLECTION_PARTIAL)
        self.assertEqual(result.termination_reason, "source_exhausted")
        self.assertEqual(result.error_summary, "评论获取未完成，已保存部分结果，可重新采集")

    async def test_invalid_platform_payload_is_failed_without_exposing_details(self):
        class InvalidResponse:
            status_code = 200

            @staticmethod
            def json():
                raise ValueError("Authorization: Bearer secret")

        class InvalidClient:
            async def get(self, *_args, **_kwargs):
                return InvalidResponse()

        result = await fetch_comments(InvalidClient(), avid=123, max_comments=3, delay=0)

        self.assertEqual(result.collection_status, COMMENT_COLLECTION_FAILED)
        self.assertEqual(result.termination_reason, "invalid_response")
        self.assertNotIn("secret", result.error_summary)

    async def test_preserves_root_and_parent_relationships(self):
        client = FakeClient([[
            make_reply(10),
            make_reply(11, root=10, parent=10),
        ]])

        comments = await fetch_comments(client, avid=123, max_comments=2, delay=0)

        self.assertEqual(comments[0]["root_rpid"], 10)
        self.assertIsNone(comments[0]["parent_rpid"])
        self.assertEqual(comments[1]["root_rpid"], 10)
        self.assertEqual(comments[1]["parent_rpid"], 10)


if __name__ == "__main__":
    unittest.main()
