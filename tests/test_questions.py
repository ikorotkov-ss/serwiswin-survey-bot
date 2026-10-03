"""Tests for question filtering and role-based logic."""

from survey_data import questions, get_questions_for_role, format_questions


class TestQuestionCount:
    """Verify total counts and distribution match the spec."""

    def test_total_questions(self):
        assert len(questions) == 45

    def test_all_question_numbers(self):
        numbers = [q["number"] for q in questions]
        assert numbers == list(range(1, 46))

    def test_five_blocks(self):
        blocks = set(q["block"] for q in questions)
        assert blocks == {"Универсальный", "Колл-центр", "Реновация окон",
                          "Мастера (выезд)", "Финальный"}

    def test_final_block_last_four(self):
        final = [q for q in questions if q["block"] == "Финальный"]
        assert [q["number"] for q in final] == [42, 43, 44, 45]

    def test_universal_block_first_15(self):
        uni = [q for q in questions if q["block"] == "Универсальный"]
        assert [q["number"] for q in uni] == list(range(1, 16))

    def test_call_center_block_16_to_25(self):
        cc = [q for q in questions if q["block"] == "Колл-центр"]
        assert [q["number"] for q in cc] == list(range(16, 26))

    def test_renovation_block_26_to_31(self):
        ren = [q for q in questions if q["block"] == "Реновация окон"]
        assert [q["number"] for q in ren] == list(range(26, 32))

    def test_masters_block_32_to_41(self):
        m = [q for q in questions if q["block"] == "Мастера (выезд)"]
        assert [q["number"] for q in m] == list(range(32, 42))


class TestRoleFiltering:
    """Verify that get_questions_for_role returns the correct question sets."""

    def test_all_role_returns_universal_and_final(self):
        """role='all' returns questions marked for everyone: universal + final = 19."""
        result = get_questions_for_role("all")
        # 15 universal + 4 final = 19 questions with role='all'
        assert len(result) == 19
        assert all(q["role"] == "all" for q in result)

    def test_sales_role_count(self):
        """Sales: all (19) + call center (10) = 29."""
        result = get_questions_for_role("sales")
        assert len(result) == 29
        # Check it contains the right mix
        blocks = set(q["block"] for q in result)
        assert "Универсальный" in blocks
        assert "Колл-центр" in blocks
        assert "Финальный" in blocks

    def test_masters_role_count(self):
        """Masters: all (19) + renovation (6) + masters-out (10) = 35."""
        result = get_questions_for_role("masters")
        assert len(result) == 35
        # Check renovation block is in there
        block_names = set(q["block"] for q in result)
        assert "Реновация окон" in block_names
        assert "Мастера (выезд)" in block_names

    def test_sales_excludes_master_blocks(self):
        result = get_questions_for_role("sales")
        for q in result:
            assert q["block"] not in ("Реновация окон", "Мастера (выезд)")

    def test_masters_excludes_sales_block(self):
        result = get_questions_for_role("masters")
        for q in result:
            assert q["block"] != "Колл-центр"


class TestBlockHelpers:
    """Test get_blocks_for_role and get_questions_in_block."""

    def test_sales_blocks_order(self):
        from survey_data import get_blocks_for_role
        blocks = get_blocks_for_role("sales")
        assert blocks == ["Универсальный", "Колл-центр", "Финальный"]

    def test_masters_blocks_order(self):
        from survey_data import get_blocks_for_role
        blocks = get_blocks_for_role("masters")
        assert blocks == ["Универсальный", "Мастера (выезд)", "Реновация окон", "Финальный"]

    def test_sales_universal_block_15_questions(self):
        from survey_data import get_questions_in_block
        qs = get_questions_in_block("Универсальный", "sales")
        assert len(qs) == 15
        assert [q["number"] for q in qs] == list(range(1, 16))

    def test_sales_call_center_block(self):
        from survey_data import get_questions_in_block
        qs = get_questions_in_block("Колл-центр", "sales")
        assert len(qs) == 10
        assert [q["number"] for q in qs] == list(range(16, 26))

    def test_sales_final_block(self):
        from survey_data import get_questions_in_block
        qs = get_questions_in_block("Финальный", "sales")
        assert len(qs) == 4
        assert [q["number"] for q in qs] == [42, 43, 44, 45]

    def test_masters_renovation_block(self):
        from survey_data import get_questions_in_block
        qs = get_questions_in_block("Реновация окон", "masters")
        assert len(qs) == 6
        assert [q["number"] for q in qs] == list(range(26, 32))

    def test_masters_field_block(self):
        from survey_data import get_questions_in_block
        qs = get_questions_in_block("Мастера (выезд)", "masters")
        assert len(qs) == 10
        assert [q["number"] for q in qs] == list(range(32, 42))


class TestOptionalHelpers:
    """Test is_optional function."""

    def test_is_optional_42(self):
        from survey_data import is_optional
        assert is_optional(42) is True

    def test_is_optional_45(self):
        from survey_data import is_optional
        assert is_optional(45) is True

    def test_is_optional_1(self):
        from survey_data import is_optional
        assert is_optional(1) is False

    def test_is_optional_99_not_found(self):
        from survey_data import is_optional
        assert is_optional(99) is False


class TestBlockWelcome:
    """Test block welcome messages."""

    def test_welcome_universal(self):
        from survey_data import get_block_welcome
        msg = get_block_welcome("Универсальный")
        assert "первый" in msg.lower() or "Первый" in msg

    def test_welcome_unknown_block(self):
        from survey_data import get_block_welcome
        msg = get_block_welcome("Блок 99")
        assert msg == "Блок: Блок 99"


class TestFormatQuestions:
    """Verify format_questions output is readable and correct."""

    def test_format_contains_role_blocks(self):
        text = format_questions("sales")
        assert "Универсальный" in text
        assert "Колл-центр" in text
        assert "Финальный" in text
        assert "Реновация" not in text
        assert "Мастера (выезд)" not in text

    def test_format_masters_has_renovation(self):
        text = format_questions("masters")
        assert "Реновация окон" in text
        assert "Мастера (выезд)" in text
        assert "Колл-центр" not in text

    def test_format_contains_numbers(self):
        text = format_questions("sales")
        for n in [1, 10, 16, 25, 42, 45]:
            assert f"{n}." in text

    def test_format_all(self):
        text = format_questions("all")
        assert "Универсальный" in text
        assert "Финальный" in text
        # all role should NOT have role-specific blocks
        assert "Колл-центр" not in text
        assert "Мастера (выезд)" not in text
