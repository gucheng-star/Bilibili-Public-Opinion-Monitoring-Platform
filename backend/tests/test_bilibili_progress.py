import unittest
from unittest.mock import AsyncMock, patch

from services.bilibili import fetch_comments


def make_reply(rpid: int):
    return {
        "rpid": rpid,
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


class BilibiliProgressTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
