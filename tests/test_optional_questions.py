"""Tests for optional question logic (questions 42 and 45)."""


# Questions 42 and 45 should be marked optional
OPTIONAL_NUMBERS = {42, 45}


def is_optional(question_number: int) -> bool:
    return question_number in OPTIONAL_NUMBERS


def count_mandatory(question_numbers: list[int]) -> int:
    return sum(1 for q in question_numbers if not is_optional(q))


def format_progress_with_optional(answered: int, total: int, optional_answered: int, total_optional: int) -> str:
    """
    Format progress bar showing mandatory + optional progress.
    E.g.:
    "📊 Прогресс: 18/23 обязательных + 1/2 опциональных"
    """
    mandatory_total = total - total_optional
    if mandatory_total <= 0:
        return f"📊 Прогресс: {optional_answered}/{total_optional} опциональных"

    mandatory_answered = answered - optional_answered
    mandatory_part = f"{mandatory_answered}/{mandatory_total} обязательных"
    if total_optional > 0:
        return f"📊 Прогресс: {mandatory_part} + {optional_answered}/{total_optional} опциональных"
    return f"📊 Прогресс: {mandatory_part}"


class TestOptionalQuestions:
    """Verify optional question logic."""

    def test_42_is_optional(self):
        assert is_optional(42) is True

    def test_45_is_optional(self):
        assert is_optional(45) is True

    def test_43_is_not_optional(self):
        assert is_optional(43) is False

    def test_44_is_not_optional(self):
        assert is_optional(44) is False

    def test_first_question_not_optional(self):
        assert is_optional(1) is False


class TestMandatoryCount:
    """Verify counting logic excludes optional questions."""

    def test_sales_has_2_optional(self):
        """Sales sees 29 questions: 2 optional (42,45) = 27 mandatory."""
        sales_questions = list(range(1, 26)) + [42, 43, 44, 45]
        # Sales actually gets 29 questions but 42+45 are the optional ones
        mandatory = count_mandatory(sales_questions)
        assert mandatory == 27

    def test_masters_has_2_optional(self):
        """Masters has 35 questions: 42 and 45 are optional = 2 optional, 33 mandatory."""
        masters_questions = list(range(1, 16)) + list(range(26, 42)) + [42, 43, 44, 45]
        mandatory = count_mandatory(masters_questions)
        assert mandatory == 33


class TestProgressWithOptional:
    """Verify progress bar formatting with optional questions."""

    def test_no_optional_yet(self):
        # 10 mandatory answered, no optional
        result = format_progress_with_optional(
            answered=10, total=25,
            optional_answered=0, total_optional=2,
        )
        assert "10/23 обязательных" in result
        assert "0/2 опциональных" in result

    def test_all_mandatory_done(self):
        result = format_progress_with_optional(
            answered=23, total=25,
            optional_answered=0, total_optional=2,
        )
        assert "23/23 обязательных" in result
        assert "0/2 опциональных" in result

    def test_all_done_including_optional(self):
        result = format_progress_with_optional(
            answered=25, total=25,
            optional_answered=2, total_optional=2,
        )
        assert "23/23 обязательных" in result
        assert "2/2 опциональных" in result

    def test_one_optional_done(self):
        result = format_progress_with_optional(
            answered=24, total=25,
            optional_answered=1, total_optional=2,
        )
        assert "23/23 обязательных" in result
        assert "1/2 опциональных" in result

    def test_no_optional_questions(self):
        result = format_progress_with_optional(
            answered=15, total=15,
            optional_answered=0, total_optional=0,
        )
        assert "15/15 обязательных" in result
