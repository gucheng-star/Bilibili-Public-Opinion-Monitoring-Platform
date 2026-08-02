"""Fixed local fixtures for evaluating sentiment labels without crawling Bilibili."""

from datetime import datetime, timedelta


FIXTURE_VIDEO_TITLE = "情感分析模拟评论测试集（不抓取）"

FIXTURE_CASES = (
    {"id": "TC-01", "rpid": 910001, "root_rpid": 910001, "parent_rpid": None, "username": "数据观察员", "content": "心脏每分钟七十次，换算下来大概就是这个量级。", "expected_emotion": "neutral", "expected_style": "plain"},
    {"id": "TC-02", "rpid": 910002, "root_rpid": 910001, "parent_rpid": 910001, "username": "提问的人", "content": "那冬眠动物也适用吗？", "expected_emotion": "neutral", "expected_style": "plain"},
    {"id": "TC-03", "rpid": 910003, "root_rpid": 910001, "parent_rpid": 910002, "username": "补充说明", "content": "视频第三分钟提到过，代谢率不同。", "expected_emotion": "neutral", "expected_style": "plain"},
    {"id": "TC-04", "rpid": 910004, "root_rpid": 910001, "parent_rpid": 910001, "username": "认真看完", "content": "讲得很清楚，感谢科普。", "expected_emotion": "support", "expected_style": "plain"},
    {"id": "TC-05", "rpid": 910010, "root_rpid": 910010, "parent_rpid": None, "username": "夜猫子", "content": "原来我每天都在消耗库存。", "expected_emotion": "joy", "expected_style": "plain"},
    {"id": "TC-06", "rpid": 910011, "root_rpid": 910010, "parent_rpid": 910010, "username": "早睡联盟", "content": "笑死，这下知道为什么要少熬夜了。", "expected_emotion": "joy", "expected_style": "meme"},
    {"id": "TC-07", "rpid": 910012, "root_rpid": 910010, "parent_rpid": 910011, "username": "复读机", "content": "DNA 动了。", "expected_emotion": "neutral", "expected_style": "meme"},
    {"id": "TC-08", "rpid": 910013, "root_rpid": 910010, "parent_rpid": 910010, "username": "求知者", "content": "求出一期讲讲乌龟的。", "expected_emotion": "anticipation", "expected_style": "plain"},
    {"id": "TC-09", "rpid": 910020, "root_rpid": 910020, "parent_rpid": None, "username": "震惊群众", "content": "居然还能这样算？", "expected_emotion": "surprise", "expected_style": "plain"},
    {"id": "TC-10", "rpid": 910021, "root_rpid": 910020, "parent_rpid": 910020, "username": "都市传说", "content": "我还以为这是都市传说。", "expected_emotion": "surprise", "expected_style": "plain"},
    {"id": "TC-11", "rpid": 910022, "root_rpid": 910020, "parent_rpid": 910020, "username": "担心一下", "content": "那长期熬夜的人风险会更高吗？", "expected_emotion": "concern", "expected_style": "plain"},
    {"id": "TC-12", "rpid": 910030, "root_rpid": 910030, "parent_rpid": None, "username": "不买账", "content": "标题党，内容和标题根本没关系。", "expected_emotion": "anger", "expected_style": "plain"},
    {"id": "TC-13", "rpid": 910031, "root_rpid": 910030, "parent_rpid": 910030, "username": "阴阳大师", "content": "对对对，所有问题都靠早睡解决，太科学了。", "expected_emotion": "anger", "expected_style": "sarcasm"},
    {"id": "TC-14", "rpid": 910032, "root_rpid": 910030, "parent_rpid": 910031, "username": "反驳一下", "content": "别阴阳怪气，他讲的是统计规律。", "expected_emotion": "anger", "expected_style": "plain"},
    {"id": "TC-15", "rpid": 910033, "root_rpid": 910030, "parent_rpid": 910030, "username": "反感流量", "content": "又拿焦虑当流量密码。", "expected_emotion": "disgust", "expected_style": "plain"},
    {"id": "TC-16", "rpid": 910040, "root_rpid": 910040, "parent_rpid": None, "username": "想起家人", "content": "外婆以前总说要早点睡，看到这里突然难受。", "expected_emotion": "sadness", "expected_style": "plain"},
    {"id": "TC-17", "rpid": 910041, "root_rpid": 910040, "parent_rpid": 910040, "username": "抱抱你", "content": "抱抱，希望大家都能照顾好自己。", "expected_emotion": "support", "expected_style": "plain"},
    {"id": "TC-18", "rpid": 910050, "root_rpid": 910050, "parent_rpid": None, "username": "不可执行", "content": "这建议可真是太有用了，毕竟谁都能做到不熬夜。", "expected_emotion": "disgust", "expected_style": "sarcasm"},
    {"id": "TC-19", "rpid": 910051, "root_rpid": 910050, "parent_rpid": 910050, "username": "现实派", "content": "确实，值夜班的人怎么办？", "expected_emotion": "concern", "expected_style": "plain"},
    {"id": "TC-20", "rpid": 910052, "root_rpid": 910050, "parent_rpid": 910051, "username": "接梗选手", "content": "建议地球停止自转，大家一起睡。", "expected_emotion": "joy", "expected_style": "meme"},
    {"id": "TC-21", "rpid": 910060, "root_rpid": 910060, "parent_rpid": None, "username": "知识收藏", "content": "UP 主这次讲得真明白，收藏了。", "expected_emotion": "support", "expected_style": "plain"},
    {"id": "TC-22", "rpid": 910061, "root_rpid": 910060, "parent_rpid": 910060, "username": "冷知识", "content": "长颈鹿的心脏压力是不是更大？", "expected_emotion": "neutral", "expected_style": "plain"},
    {"id": "TC-23", "rpid": 910070, "root_rpid": 910070, "parent_rpid": None, "username": "短评用户", "content": "6。", "expected_emotion": "surprise", "expected_style": "meme"},
    {"id": "TC-24", "rpid": 910071, "root_rpid": 910070, "parent_rpid": 910070, "username": "看懂了", "content": "这下彻底明白了。", "expected_emotion": "support", "expected_style": "plain"},
)


def build_fixture_comments() -> list[dict]:
    """Return a fresh comment list with stable timestamps and tree relationships."""
    base_time = datetime(2026, 8, 2, 12, 0)
    comments = []
    for index, case in enumerate(FIXTURE_CASES):
        comments.append({
            "rpid": case["rpid"],
            "root_rpid": case["root_rpid"],
            "parent_rpid": case["parent_rpid"],
            "username": case["username"],
            "gender": "保密",
            "ip_location": "IP属地：测试",
            "content": case["content"],
            "likes": 24 - index,
            "post_time": base_time + timedelta(minutes=index),
        })
    return comments


def fixture_case_catalog() -> list[dict]:
    """Expose expectations for manual evaluation without persisting them as model output."""
    return [
        {
            "id": case["id"],
            "rpid": case["rpid"],
            "expected_emotion": case["expected_emotion"],
            "expected_style": case["expected_style"],
            "content": case["content"],
        }
        for case in FIXTURE_CASES
    ]
