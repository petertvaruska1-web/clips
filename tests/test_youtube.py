from clipforge.config import YouTubeCfg
from clipforge.youtube import build_metadata


def test_metadata_has_credit_tags_and_privacy():
    body = build_metadata(title="Kai Cenat can't stop laughing in GTA 6 😭", streamer="kaicenat",
                          display="Kai Cenat", hashtags=["#GTA6", "#funny"], cfg=YouTubeCfg(privacy="public"))
    s = body["snippet"]
    assert s["title"].startswith("Kai Cenat") and len(s["title"]) <= 100 and "#GTA6" in s["title"]
    assert "twitch.tv/kaicenat" in s["description"]
    assert s["categoryId"] == "20"
    assert body["status"]["privacyStatus"] == "public"
    assert body["status"]["selfDeclaredMadeForKids"] is False


def test_title_is_trimmed_to_100():
    body = build_metadata(title="x" * 200, streamer="a", display="A", hashtags=[], cfg=YouTubeCfg())
    assert len(body["snippet"]["title"]) <= 100


def test_metadata_credits_background_footage():
    from clipforge.config import YouTubeCfg
    body = build_metadata("t", "kaicenat", "KaiCenat", [], YouTubeCfg(), bg_credit="Orbital (CC BY) https://youtu.be/x")
    assert "Background gameplay: Orbital (CC BY)" in body["snippet"]["description"]
    assert "Background gameplay" not in build_metadata("t", "k", "K", [], YouTubeCfg())["snippet"]["description"]
