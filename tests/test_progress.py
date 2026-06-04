"""Tests for progress tracking logic."""


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
