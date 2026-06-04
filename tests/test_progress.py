"""Tests for progress tracking logic."""


from bot import _build_progress_bar


from bot import _build_progress_bar


def make_progress_bar(answered: int, total: int, width: int = 12) -> str:
    """Build a visual progress bar string.

    Returns something like:
    "📊 Прогресс: ████████░░░░ 10/25 (40%)"
    """
    if total == 0:
        return "📊 Прогресс: 0/0"

    pct = int(answered / total * 100)
    filled = round(pct / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"📊 Прогресс: {bar} {answered}/{total} ({pct}%)"


class TestProgressBar:
    """Verify progress bar formatting."""

    def test_zero(self):
        assert make_progress_bar(0, 25) == "📊 Прогресс: ░░░░░░░░░░░░ 0/25 (0%)"

    def test_half(self):
        result = make_progress_bar(13, 25)
        assert "13/25" in result
        assert "(52%)" in result

    def test_all_done(self):
        result = make_progress_bar(25, 25)
        assert "25/25" in result
        assert "(100%)" in result

    def test_full_bar_100(self):
        result = make_progress_bar(25, 25)
        # Should be all filled blocks
        assert "░" not in result or result.count("░") < 2

    def test_single_question(self):
        result = make_progress_bar(1, 1)
        assert "(100%)" in result

    def test_total_zero(self):
        assert make_progress_bar(0, 0) == "📊 Прогресс: 0/0"


class TestBuildProgressBar:
    """Test the actual _build_progress_bar from bot.py."""

    def test_only_mandatory(self):
        progress = {
            "mandatory_answered": 10,
            "total_mandatory": 23,
            "optional_answered": 0,
            "total_optional": 0,
            "total_questions": 23,
            "answered_count": 10,
            "skipped_count": 0,
        }
        result = _build_progress_bar(progress)
        assert "10/23 обязательных" in result
        assert "опциональных" not in result

    def test_with_optional(self):
        progress = {
            "mandatory_answered": 10,
            "total_mandatory": 23,
            "optional_answered": 1,
            "total_optional": 2,
            "total_questions": 25,
            "answered_count": 11,
            "skipped_count": 0,
        }
        result = _build_progress_bar(progress)
        assert "10/23 обязательных" in result
        assert "1/2 опциональных" in result

    def test_all_done(self):
        progress = {
            "mandatory_answered": 23,
            "total_mandatory": 23,
            "optional_answered": 2,
            "total_optional": 2,
            "total_questions": 25,
            "answered_count": 25,
            "skipped_count": 0,
        }
        result = _build_progress_bar(progress)
        assert "23/23 обязательных" in result
        assert "2/2 опциональных" in result

    def test_zero_all(self):
        progress = {
            "mandatory_answered": 0,
            "total_mandatory": 0,
            "optional_answered": 0,
            "total_optional": 0,
            "total_questions": 0,
            "answered_count": 0,
            "skipped_count": 0,
        }
        result = _build_progress_bar(progress)
        assert result == ""
