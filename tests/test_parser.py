"""Tests for parse_question_number — imports real function from transcriber."""
import pytest
from transcriber import parse_question_number


class TestParseQuestionNumber:
    """Verify question number extraction from text."""

    # ── Happy path: russian prefixes ────────────────────────────────

    def test_vopros_prefix(self):
        assert parse_question_number("Вопрос 5. клиент сказал что дорого") == 5

    def test_vopros_prefix_no_dot(self):
        assert parse_question_number("Вопрос 5 клиент сказал") == 5

    def test_nomer_prefix(self):
        assert parse_question_number("номер 12 ответ") == 12

    def test_digit_and_dot(self):
        assert parse_question_number("5. клиент сказал") == 5

    def test_digit_and_paren(self):
        assert parse_question_number("7) ответ на вопрос") == 7

    def test_plain_digit(self):
        assert parse_question_number("3") == 3

    def test_double_digit(self):
        assert parse_question_number("42") == 42

    # ── English prefixes ────────────────────────────────────────────

    def test_question_english(self):
        assert parse_question_number("question 8...") == 8

    def test_pytanie_polish(self):
        assert parse_question_number("pytanie 15") == 15

    # ── Lowercase, extra spaces, punctuation ────────────────────────

    def test_lowercase(self):
        assert parse_question_number("вопрос 30...") == 30

    def test_trailing_periods(self):
        assert parse_question_number("Вопрос 3....") == 3

    # ── Edge cases: out of range ────────────────────────────────────

    def test_zero_not_valid(self):
        assert parse_question_number("0") is None

    def test_minus_one_not_valid(self):
        assert parse_question_number("-1") is None

    def test_above_max(self):
        assert parse_question_number("46") is None

    def test_99_not_valid(self):
        assert parse_question_number("99") is None

    # ── Edge cases: no number ───────────────────────────────────────

    def test_no_number(self):
        assert parse_question_number("клиент сказал что дорого") is None

    def test_empty_string(self):
        assert parse_question_number("") is None

    def test_none_input(self):
        assert parse_question_number(None) is None

    def test_only_spaces(self):
        assert parse_question_number("   ") is None

    # ── Edge cases: tricky ──────────────────────────────────────────

    def test_number_in_middle_not_extracted(self):
        """Only numbers at the beginning are extracted."""
        assert parse_question_number("я ответил на вопрос 5") is None

    def test_number_attached_to_word_follows_prefix(self):
        """вопрос5 (no space) is ambiguous but still valid — the 0+ space
        between prefix and digit catches it. Acceptable UX."""
        assert parse_question_number("вопрос5") == 5

    def test_leading_zeros(self):
        assert parse_question_number("05") == 5

    def test_question_mark_after_digit(self):
        assert parse_question_number("5?") == 5

    def test_newlines_before(self):
        assert parse_question_number("\n\nВопрос 5") == 5

    def test_multiple_question_numbers_first_wins(self):
        """If user mentions two questions, take the first."""
        result = parse_question_number("Вопрос 5 и вопрос 12")
        assert result == 5
