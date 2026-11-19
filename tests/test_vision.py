from clipforge.judge import frames_have_nudity


def test_any_frame_with_nudity_blocks():
    answers = iter(['```json\n{"nudity": false}\n```', '{"nudity": true, "what": "bare buttocks"}'])
    assert frames_have_nudity([b"a", b"b"], key="k", caller=lambda key, jpg: next(answers)) is True


def test_clean_frames_pass():
    assert frames_have_nudity([b"a", b"b"], key="k", caller=lambda key, jpg: '{"nudity": false}') is False


def test_no_key_or_errors_do_not_block():
    assert frames_have_nudity([b"a"], key="", caller=lambda k, j: '{"nudity": true}') is None

    def boom(k, j):
        raise RuntimeError("down")
    assert frames_have_nudity([b"a"], key="k", caller=boom) is None
