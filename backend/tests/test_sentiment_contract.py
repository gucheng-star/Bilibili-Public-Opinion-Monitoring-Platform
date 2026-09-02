import unittest

from services.sentiment_contract import (
    LLM_SENTIMENT_SCHEMA_NONE,
    LLM_SENTIMENT_SCHEMA_V1,
    LLM_SENTIMENT_SCHEMA_V2,
    V1_EMOTION_LABELS,
    V2Emotion,
    V2_EMOTION_LABELS,
    V2Style,
    V2_STYLE_LABELS,
)


class SentimentContractTests(unittest.TestCase):
    def test_schema_versions_are_stable_and_ordered(self):
        self.assertEqual(
            (LLM_SENTIMENT_SCHEMA_NONE, LLM_SENTIMENT_SCHEMA_V1, LLM_SENTIMENT_SCHEMA_V2),
            (0, 1, 2),
        )

    def test_v2_emotions_are_exactly_the_nine_supported_values(self):
        self.assertEqual(
            V2_EMOTION_LABELS,
            {
                "neutral", "joy", "trust", "anticipation", "surprise",
                "anger", "sadness", "fear", "disgust",
            },
        )
        self.assertTrue({"support", "concern", "sarcasm"}.isdisjoint(V2_EMOTION_LABELS))
        self.assertEqual({emotion.value for emotion in V2Emotion}, V2_EMOTION_LABELS)

    def test_v2_styles_are_exactly_the_five_supported_values(self):
        self.assertEqual(
            V2_STYLE_LABELS,
            {"plain", "sarcasm", "meme", "rhetorical", "hyperbole"},
        )
        self.assertEqual({style.value for style in V2Style}, V2_STYLE_LABELS)

    def test_v1_labels_are_only_for_historical_migration(self):
        self.assertIn("support", V1_EMOTION_LABELS)
        self.assertIn("concern", V1_EMOTION_LABELS)
        self.assertIn("sarcasm", V1_EMOTION_LABELS)
        self.assertTrue({"trust", "fear"}.isdisjoint(V1_EMOTION_LABELS))


if __name__ == "__main__":
    unittest.main()
