"""Terminal prompts — menu parsing is the part that can silently pick the wrong thing."""

from __future__ import annotations

import pytest

from src.claude_pm.commands._prompt import Choice, choose, is_interactive
from src.claude_pm.commands._prompt import _parse_selection as parse
from src.claude_pm.exceptions import PMError

OPTIONS = [Choice(id="a", label="A"), Choice(id="b", label="B"), Choice(id="c", label="C")]


class TestSingleSelection:
    def test_picks_by_one_based_number(self) -> None:
        assert parse("2", 3, multi=False) == [1]

    def test_surrounding_whitespace_is_fine(self) -> None:
        assert parse("  2  ", 3, multi=False) == [1]

    @pytest.mark.parametrize("raw", ["", "0", "4", "-1", "abc", "2.5", "1 2", "1,2"])
    def test_rejects_anything_ambiguous_or_out_of_range(self, raw: str) -> None:
        assert parse(raw, 3, multi=False) == []


class TestMultiSelection:
    def test_comma_separated(self) -> None:
        assert parse("1,3", 3, multi=True) == [0, 2]

    def test_space_separated(self) -> None:
        assert parse("1 3", 3, multi=True) == [0, 2]

    def test_order_follows_the_answer(self) -> None:
        assert parse("3,1", 3, multi=True) == [2, 0]

    def test_all_keywords(self) -> None:
        for word in ("todos", "todas", "all", "*", "TODOS"):
            assert parse(word, 3, multi=True) == [0, 1, 2]

    def test_a_repeated_number_is_rejected(self) -> None:
        """Silently de-duplicating would hide a typo in a destructive-ish choice."""
        assert parse("1,1", 3, multi=True) == []

    def test_one_bad_entry_rejects_the_whole_answer(self) -> None:
        assert parse("1,9", 3, multi=True) == []

    def test_all_is_not_a_single_select_word(self) -> None:
        assert parse("todos", 3, multi=False) == []


class TestChoose:
    def test_a_single_option_is_taken_without_asking(self, capsys) -> None:
        assert choose("which one?", OPTIONS[:1]) == ["a"]
        assert "only option" in capsys.readouterr().out

    def test_multi_still_asks_even_with_one_option(self, monkeypatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _: "1")
        assert choose("which ones?", OPTIONS[:1], multi=True) == ["a"]

    def test_it_reasks_until_the_answer_parses(self, monkeypatch, capsys) -> None:
        answers = iter(["9", "nope", "2"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        assert choose("which one?", OPTIONS) == ["b"]
        assert capsys.readouterr().out.count("Didn't understand") == 2

    def test_no_options_is_an_error_not_a_hang(self) -> None:
        with pytest.raises(PMError, match="no options"):
            choose("which one?", [])

    def test_eof_is_a_clean_cancel(self, monkeypatch) -> None:
        def raise_eof(_: str) -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        with pytest.raises(PMError, match="Cancelled"):
            choose("which one?", OPTIONS)


class TestInteractiveDetection:
    def test_a_pipe_is_not_interactive(self, monkeypatch) -> None:
        """This is what keeps Claude on the exit-2 protocol."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        assert is_interactive() is False

    def test_a_closed_stream_is_not_interactive(self, monkeypatch) -> None:
        def boom() -> bool:
            raise ValueError("I/O operation on closed file")

        monkeypatch.setattr("sys.stdin.isatty", boom)
        assert is_interactive() is False
