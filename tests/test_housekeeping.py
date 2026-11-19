import os

import pytest

from clipforge.app import safe_unlink


def test_safe_unlink_removes_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert safe_unlink(f) is True and not f.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows file locking")
def test_safe_unlink_survives_locked_file(tmp_path):
    f = tmp_path / "locked.part"
    f.write_text("x")
    with open(f, "r"):
        assert safe_unlink(f) is False
