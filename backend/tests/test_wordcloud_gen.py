import unittest

from services.wordcloud_gen import get_top_keywords


class WordCloudKeywordTests(unittest.TestCase):
    def test_bilibili_emotes_are_removed_without_hiding_normal_words(self):
        keywords = get_top_keywords([{
            "content": (
                "拥抱 支持 [拥抱][支持][doge][doge_金箍] "
                "真实讨论 [星绘·沐春灼华 应援装扮_对]"
            ),
        }], top_n=50)
        counts = {item["word"]: item["count"] for item in keywords}

        self.assertEqual(counts.get("拥抱"), 1)
        self.assertEqual(counts.get("支持"), 1)
        self.assertNotIn("金箍", counts)
        self.assertIn("真实", counts)
        self.assertIn("讨论", counts)

    def test_comments_containing_only_bilibili_emotes_have_no_keywords(self):
        keywords = get_top_keywords([{
            "content": "[拥抱][笑哭][doge][doge_金箍]",
        }])

        self.assertEqual(keywords, [])


if __name__ == "__main__":
    unittest.main()
