from clipforge.db import Database


def test_moment_roundtrip(tmp_path):
    db = Database(tmp_path / "x.db")
    mid = db.add_moment(channel="kaicenat", t_event=100.0, t_on=107.0, t_peak=110.0,
                        score=0.5, category="funny", features={"z": 3.1})
    db.update_moment(mid, state="rendered", score=0.8, out_path="a.mp4")
    m = db.get_moment(mid)
    assert m["state"] == "rendered" and m["score"] == 0.8 and m["features"]["z"] == 3.1
    assert [r["id"] for r in db.moments_in_state("rendered")] == [mid]


def test_uploads_count(tmp_path):
    db = Database(tmp_path / "x.db")
    mid = db.add_moment(channel="xqc", t_event=1.0, t_on=2.0, t_peak=3.0, score=0.9,
                        category="hype", features={})
    db.add_upload(mid, video_id="abc", title="t", channel="xqc", published_at=1000.0, exceptional=False)
    ups = db.uploads_since(0)
    assert ups[0]["channel"] == "xqc" and ups[0]["video_id"] == "abc"
