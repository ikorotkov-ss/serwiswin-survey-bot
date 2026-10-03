"""Tests for callback routing: verify ALL callback_data patterns are handled.

The bot registers CallbackQueryHandler with a regex pattern. If a callback
is created but the pattern doesn't match, the button does nothing (silent fail).

This test extracts both the registered patterns and the callback_data values
used in the code, and verifies they're all covered.
"""
import re
import os
import sys
import ast

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_callback_pattern_from_bot():
    """Extract the regex pattern string from bot.py's CallbackQueryHandler registration."""
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.py"), "r") as f:
        source = f.read()

    # Find lines that register CallbackQueryHandler with pattern=
    pattern_search = re.search(
        r'CallbackQueryHandler\(button_handler,\s*pattern="([^"]+)"\)',
        source,
    )
    if pattern_search:
        return pattern_search.group(1)
    return None


def _get_all_callback_data_in_code():
    """Parse all callback_data= string literals from bot.py using AST."""
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.py"), "r") as f:
        source = f.read()

    tree = ast.parse(source)

    callbacks = set()
    for node in ast.walk(tree):
        # Look for callback_data= in function calls
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "callback_data" and isinstance(kw.value, ast.Constant):
                    callbacks.add(kw.value.value)
                elif kw.arg == "callback_data" and isinstance(kw.value, ast.JoinedStr):
                    # F-string like f"append_{qnum}" — extract the static part
                    for val in kw.value.values:
                        if isinstance(val, ast.Constant):
                            callbacks.add(val.value)

    return callbacks


def _check_callback_matches(pattern_str: str, callback: str) -> bool:
    """Check if a callback value matches the pattern regex."""
    compiled = re.compile(pattern_str)
    return bool(compiled.match(callback))


class TestCallbackRouting:
    """Every callback_data created in bot.py must match the handler pattern."""

    def test_pattern_exists(self):
        pattern = _get_callback_pattern_from_bot()
        assert pattern is not None, "No CallbackQueryHandler pattern found in bot.py"

    def test_all_known_callbacks_match(self):
        pattern = _get_callback_pattern_from_bot()
        assert pattern is not None

        # Manually enumerate ALL callback_data values used in bot.py
        # (role_sales/role_masters are handled by role_callback, not button_handler)
        expected_callbacks = {
            # Renovation prompt
            "renovation_yes",
            "renovation_no",
            # Navigation
            "next_part",
            "next_block",
            "finish_survey",
            # Append pattern (variable part)
            "append_1",
            "append_5",
            "append_42",
        }

        for cb in expected_callbacks:
            assert _check_callback_matches(pattern, cb), (
                f"Callback '{cb}' does NOT match pattern '{pattern}'"
            )

    def test_role_callbacks_have_separate_handler(self):
        """role_sales and role_masters are handled by role_callback, not button_handler."""
        pattern_role = _get_callback_pattern_from_bot()
        assert "role_" not in pattern_role, (
            "role_ callbacks should NOT be in button_handler pattern"
        )

    def test_role_pattern_matches_role_callbacks(self):
        """Verify the role_callback handler pattern."""
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.py"), "r") as f:
            source = f.read()

        role_pattern = re.search(
            r'CallbackQueryHandler\(role_callback,\s*pattern="([^"]+)"\)',
            source,
        )
        assert role_pattern is not None, "No role_callback handler found"
        compiled = re.compile(role_pattern.group(1))
        assert compiled.match("role_sales")
        assert compiled.match("role_masters")
        assert not compiled.match("next_block")
        assert not compiled.match("append_5")

    def test_no_callback_overlap_between_handlers(self):
        """A callback should match ONLY one handler (button_handler or role_callback)."""
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.py"), "r") as f:
            source = f.read()

        role_pattern_str = re.search(
            r'CallbackQueryHandler\(role_callback,\s*pattern="([^"]+)"\)', source
        ).group(1)
        button_pattern_str = re.search(
            r'CallbackQueryHandler\(button_handler,\s*pattern="([^"]+)"\)', source
        ).group(1)

        role_re = re.compile(role_pattern_str)
        button_re = re.compile(button_pattern_str)

        # Check known role callbacks
        for cb in ["role_sales", "role_masters"]:
            assert role_re.match(cb), f"{cb} should match role handler"
            assert not button_re.match(cb), f"{cb} should NOT match button handler"

        # Check known button callbacks
        for cb in ["next_block", "next_part", "finish_survey", "renovation_yes", "renovation_no"]:
            assert button_re.match(cb), f"{cb} should match button handler"
            assert not role_re.match(cb), f"{cb} should NOT match role handler"

    def test_append_pattern_with_any_number(self):
        """append_ prefix with any number should match."""
        pattern = _get_callback_pattern_from_bot()
        compiled = re.compile(pattern)

        for n in [1, 5, 12, 33, 45]:
            assert compiled.match(f"append_{n}"), f"append_{n} should match"

    def test_no_orphan_button_creations(self):
        """Every callback_data in bot.py should be handled by SOME handler."""
        pattern = _get_callback_pattern_from_bot()
        compiled = re.compile(pattern)

        # Also check role handler
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.py"), "r") as f:
            source = f.read()
        role_pattern_str = re.search(
            r'CallbackQueryHandler\(role_callback,\s*pattern="([^"]+)"\)', source
        ).group(1)
        role_re = re.compile(role_pattern_str)

        # Collect all callback_data from the source
        callbacks = _get_all_callback_data_in_code()
        for cb in callbacks:
            assert compiled.match(cb) or role_re.match(cb), (
                f"callback_data '{cb}' is not handled by any registered handler!"
            )
