"""Tests for skipped question logic (skip button, return after block, return on re-entry)."""


class UserSession:
    """Simplified simulation of user survey session state."""

    def __init__(self, user_id, role, total_questions):
        self.user_id = user_id
        self.role = role
        self.total = total_questions  # total questions for this role
        self.answers = {}  # question_number -> "answered" | "skipped"
        self.current_block_questions = []
        self.current_block_index = 0
        self.block_question_ranges = []
        self.completed_blocks = []
        self.finished = False

    def answer(self, qnum: int):
        self.answers[qnum] = "answered"

    def skip(self, qnum: int):
        self.answers[qnum] = "skipped"

    def has_skipped_in_block(self, block_range: range) -> list[int]:
        return [q for q in block_range if self.answers.get(q) == "skipped"]

    def all_answered_or_skipped(self, block_range: range) -> bool:
        return all(q in self.answers for q in block_range)

    def get_skipped_questions(self) -> list[int]:
        return sorted([q for q, s in self.answers.items() if s == "skipped"])


def get_next_unanswered(user: UserSession, block_questions: list[int]) -> int | None:
    """Get next unanswered non-skipped question in current block."""
    for q in block_questions:
        if q not in user.answers:
            return q
    return None


def should_offer_skipped(user: UserSession, block_range: range) -> bool:
    """Should we offer to return to skipped questions after a block is done?"""
    if not user.all_answered_or_skipped(block_range):
        return False
    skipped = user.has_skipped_in_block(block_range)
    return len(skipped) > 0


def should_offer_skipped_on_reentry(user: UserSession) -> bool:
    """Should we offer skipped questions when user re-enters the bot?"""
    # Check if user has any skipped questions across all blocks
    return len(user.get_skipped_questions()) > 0


class TestSkipDuringSurvey:
    """Verify skip mechanism during active survey."""

    def test_skip_marks_as_skipped(self):
        session = UserSession(1, "sales", 25)
        session.skip(5)
        assert session.answers[5] == "skipped"

    def test_skip_moves_to_next(self):
        session = UserSession(1, "sales", 25)
        session.skip(1)
        next_q = get_next_unanswered(session, [1, 2, 3, 4, 5])
        assert next_q == 2  # should skip to next

    def test_next_after_partial_answers(self):
        session = UserSession(1, "sales", 25)
        session.answer(1)
        session.answer(2)
        session.skip(3)
        session.answer(4)
        next_q = get_next_unanswered(session, [1, 2, 3, 4, 5])
        assert next_q == 5

    def test_all_answered_returns_none(self):
        session = UserSession(1, "sales", 25)
        for q in [1, 2, 3]:
            session.answer(q)
        next_q = get_next_unanswered(session, [1, 2, 3])
        assert next_q is None


class TestReturnToSkippedAfterBlock:
    """Verify that after finishing a block, user is offered skipped questions (Variant A)."""

    def test_no_skipped_in_block(self):
        session = UserSession(1, "sales", 25)
        block = range(1, 16)  # universal block
        for q in block:
            session.answer(q)
        assert should_offer_skipped(session, block) is False

    def test_has_skipped_in_block(self):
        session = UserSession(1, "sales", 25)
        block = range(1, 16)
        for q in block:
            if q in (3, 7, 12):
                session.skip(q)
            else:
                session.answer(q)
        assert should_offer_skipped(session, block) is True

    def test_skipped_list_correct(self):
        session = UserSession(1, "sales", 25)
        block = range(1, 16)
        for q in block:
            if q in (3, 7, 12):
                session.skip(q)
            else:
                session.answer(q)
        assert session.has_skipped_in_block(block) == [3, 7, 12]

    def test_partial_block_no_offer(self):
        """If block not completed, don't offer skipped questions."""
        session = UserSession(1, "sales", 25)
        block = range(1, 16)
        for q in range(1, 10):
            session.answer(q)
        # 10-15 not answered yet
        assert should_offer_skipped(session, block) is False


class TestReturnOnReentry:
    """Verify that on re-entry, skipped questions are offered first (Variant C)."""

    def test_no_skipped_no_offer(self):
        session = UserSession(1, "sales", 25)
        session.answer(1)
        assert should_offer_skipped_on_reentry(session) is False

    def test_skipped_offers_on_reentry(self):
        session = UserSession(1, "sales", 25)
        session.skip(5)
        assert should_offer_skipped_on_reentry(session) is True

    def test_multiple_skipped_offers_on_reentry(self):
        session = UserSession(1, "sales", 25)
        session.skip(3)
        session.skip(7)
        session.skip(12)
        assert should_offer_skipped_on_reentry(session) is True
        assert session.get_skipped_questions() == [3, 7, 12]

    def test_answered_skipped_then_answered(self):
        """If skipped question is later answered, it shouldn't be offered."""
        session = UserSession(1, "sales", 25)
        session.skip(5)
        assert session.get_skipped_questions() == [5]
        # Now answer it (e.g. after returning to it)
        session.answer(5)
        assert session.get_skipped_questions() == []
        assert should_offer_skipped_on_reentry(session) is False
