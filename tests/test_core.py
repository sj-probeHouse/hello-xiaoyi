import pytest

from xiaoyi.core import CopyGesture, capture_is_fresh, normalize_text, translation_prompt


def test_double_copy_requires_two_distinct_presses():
    gesture = CopyGesture()
    assert not gesture.feed("ctrl", True, 0)
    assert not gesture.feed("c", True, 0.1)
    assert not gesture.feed("c", True, 0.2)  # autorepeat
    assert not gesture.feed("c", False, 0.21)
    assert gesture.feed("c", True, 0.3)


@pytest.mark.parametrize("interruption", ["ctrl", "other", "shift"])
def test_interrupted_chord_does_not_fire(interruption):
    gesture = CopyGesture()
    gesture.feed("ctrl", True, 0)
    gesture.feed("c", True, 0.1)
    gesture.feed("c", False, 0.11)
    gesture.feed(interruption, interruption != "ctrl", 0.2)
    assert not gesture.feed("c", True, 0.3)


def test_slow_or_paused_gesture_does_not_fire():
    gesture = CopyGesture()
    gesture.feed("ctrl", True, 0)
    gesture.feed("c", True, 0.1)
    gesture.feed("c", False, 0.2)
    assert not gesture.feed("c", True, 0.8)
    gesture.reset()
    assert not gesture.feed("c", True, 0.9)


def test_stale_clipboard_and_window_switch_rejected():
    assert capture_is_fresh(20, 21, 100, 100, "new text")
    assert not capture_is_fresh(20, 20, 100, 100, "old text")
    assert not capture_is_fresh(20, 21, 100, 101, "other window")
    assert not capture_is_fresh(20, 21, 100, 100, "  ")


def test_pdf_cleanup_preserves_paragraphs_formula_and_hyphenation():
    assert normalize_text("A soft\u00adhyphen\r\nwrap.\n\nE = mc² [3].") == (
        "A softhyphen wrap.\n\nE = mc² [3]."
    )
    # Keep visible hyphens: a line break alone cannot distinguish a compound from a split word.
    assert normalize_text("state-\nof-the-art") == "state-of-the-art"


def test_text_limits_and_english_detection():
    with pytest.raises(ValueError, match="英文"):
        normalize_text("只有中文")
    with pytest.raises(ValueError, match="分段"):
        normalize_text("a" * 8001)
    with pytest.raises(ValueError):
        normalize_text("")


def test_word_prompt_does_not_invent_context():
    assert "学术义" in translation_prompt("attention", "计算机")
    assert "上下文" in translation_prompt("attention", "计算机")
    assert "公式" in translation_prompt("We use attention.", "计算机")
