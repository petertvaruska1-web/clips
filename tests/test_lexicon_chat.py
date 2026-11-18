from clipforge.lexicon import normalize, categorize
from clipforge.chat import parse_irc


def test_normalize_collapses_repeats_and_case():
    assert normalize("LMAOOOO KEKW") == ["lmao", "kekw"]


def test_normalize_keeps_question_storm_as_token():
    assert "???" in normalize("WHAT??????")


def test_categorize_funny():
    assert categorize(["kekw"]) == {"funny"}


def test_categorize_clip_request():
    assert "clip" in categorize(["clip", "it"])


def test_categorize_learned_tokens():
    assert "funny" in categorize(["xyzlaugh"], learned={"xyzlaugh": "funny"})


PRIV = ("@badge-info=;badges=subscriber/12;color=#FF0000;display-name=Bob;emotes=;first-msg=0;"
        "id=abc;mod=0;room-id=123;subscriber=1;tmi-sent-ts=1700000000123;user-id=999 "
        ":bob!bob@bob.tmi.twitch.tv PRIVMSG #kaicenat :KEKW no way")
RAID = ("@display-name=Raider;login=raider;msg-id=raid;msg-param-viewerCount=500;room-id=123;"
        "tmi-sent-ts=1700000001000;user-id=5 :tmi.twitch.tv USERNOTICE #kaicenat")


def test_parse_privmsg():
    ev = parse_irc(PRIV)
    assert ev.kind == "msg" and ev.channel == "kaicenat"
    assert ev.ts == 1700000000.123
    assert ev.text == "KEKW no way"
    assert ev.user != "999" and len(ev.user) == 12  # hashed
    assert ev.extra["sub"] is True


def test_parse_raid():
    ev = parse_irc(RAID)
    assert ev.kind == "raid" and ev.extra["viewers"] == 500


def test_parse_ping_and_garbage():
    assert parse_irc("PING :tmi.twitch.tv").kind == "ping"
    assert parse_irc(":tmi.twitch.tv 001 justinfan123 :Welcome") is None
