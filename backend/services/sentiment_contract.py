"""Versioned contracts for persisted LLM sentiment results.

This module intentionally contains only stable data-contract definitions.  Model
prompts, provider requests, and result routing remain in their own later phases.
"""

from enum import Enum

LLM_SENTIMENT_SCHEMA_NONE = 0
LLM_SENTIMENT_SCHEMA_V1 = 1
LLM_SENTIMENT_SCHEMA_V2 = 2

# Historical primary labels are retained solely to identify existing V1 rows
# during migration.  They are not a V2 output contract.
V1_EMOTION_LABELS = frozenset({
    "neutral", "joy", "support", "anticipation", "surprise",
    "anger", "sadness", "concern", "disgust", "sarcasm",
})


class V2Emotion(str, Enum):
    NEUTRAL = "neutral"
    JOY = "joy"
    TRUST = "trust"
    ANTICIPATION = "anticipation"
    SURPRISE = "surprise"
    ANGER = "anger"
    SADNESS = "sadness"
    FEAR = "fear"
    DISGUST = "disgust"


class V2Style(str, Enum):
    PLAIN = "plain"
    SARCASM = "sarcasm"
    MEME = "meme"
    RHETORICAL = "rhetorical"
    HYPERBOLE = "hyperbole"


V2_EMOTION_LABELS = frozenset(emotion.value for emotion in V2Emotion)
V2_STYLE_LABELS = frozenset(style.value for style in V2Style)
