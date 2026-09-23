"""The wizard, and the guarantee that it did not disturb the machine protocol.

`pm init` has two consumers. A person gets questions; Claude gets exit 2 with a
payload. The second must stay exactly as it was, so the tests here assert both
sides of the same code path.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from src.claude_pm.commands import init
from src.claude_pm.exceptions import NeedsChoice, PMError


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "repo_name": None,
        "profile": None,
        "provider": None,
        "workspace_id": None,
        "space_id": None,
        "list_id": None,
        "from_legacy": None,
        "force": False,
        "dry_run": False,
        "no_input": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestMachineProtocolUnchanged:
    def test_no_input_never_prompts_even_on_a_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(init, "is_interactive", lambda: True)
        monkeypatch.setattr(
            init,
            "_run_once",
            lambda _a: (_ for _ in ()).throw(NeedsChoice("pick", {"action": "x"})),
        )
        monkeypatch.setattr("builtins.input", lambda _: pytest.fail("prompted despite --no-input"))
        with pytest.raises(NeedsChoice):
            init.run(_args(no_input=True))

    def test_without_a_tty_the_payload_comes_back_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {"action": "choose-workspace", "workspaces": [{"id": "w1", "name": "One"}]}
        monkeypatch.setattr(init, "is_interactive", lambda: False)
        monkeypatch.setattr(
            init, "_run_once", lambda _a: (_ for _ in ()).throw(NeedsChoice("pick", payload))
        )
        with pytest.raises(NeedsChoice) as excinfo:
            init.run(_args())
        assert excinfo.value.payload == payload
        assert excinfo.value.exit_code == 2


class TestWizardLoop:
    def _answers(self, monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
        stream = iter(answers)
        monkeypatch.setattr("builtins.input", lambda _: next(stream))

    def test_it_answers_each_question_and_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payloads = [
            {
                "action": "choose-workspace",
                "workspaces": [{"id": "w1", "name": "A"}, {"id": "w2", "name": "B"}],
            },
            {
                "action": "choose-list",
                "lists": [{"id": "l1", "name": "X"}, {"id": "l2", "name": "Y"}],
            },
        ]
        seen: list[argparse.Namespace] = []

        def fake_run_once(args: argparse.Namespace) -> int:
            seen.append(args)
            if payloads:
                raise NeedsChoice("pick", payloads.pop(0))
            return 0

        monkeypatch.setattr(init, "is_interactive", lambda: True)
        monkeypatch.setattr(init, "list_profiles", lambda: [object()])
        monkeypatch.setattr(init, "_run_once", fake_run_once)
        self._answers(monkeypatch, ["2", "1,2"])

        args = _args()
        assert init.run(args) == 0
        assert args.workspace_id == "w2"
        assert args.list_id == ["l1", "l2"]
        assert len(seen) == 3

    def test_an_unknown_action_is_reported_not_ignored(self) -> None:
        with pytest.raises(PMError, match="de forma interactiva"):
            init._answer(_args(), {"action": "choose-something-new"})


class TestOptionShapes:
    """Payloads carry options in a few shapes; the menu has to read all of them."""

    def test_id_and_name(self) -> None:
        options = init._options([{"id": "w1", "name": "Urbs Data"}])
        assert (options[0].id, options[0].label, options[0].detail) == ("w1", "Urbs Data", "w1")

    def test_plain_strings(self) -> None:
        options = init._options(["clickup", "linear"])
        assert [o.id for o in options] == ["clickup", "linear"]
        assert options[0].label == "clickup"

    def test_a_redacted_profile_uses_its_name_as_the_id(self) -> None:
        options = init._options(
            [{"name": "urbs", "provider": "clickup", "workspace_id": None, "token": "…1234"}]
        )
        assert options[0].id == "urbs"
        assert options[0].detail == "clickup"

    def test_a_token_never_reaches_the_menu(self) -> None:
        options = init._options([{"name": "urbs", "provider": "clickup", "token": "…1234"}])
        assert "1234" not in (options[0].label + options[0].detail)


class TestFirstCredential:
    def test_the_wizard_asks_for_a_token_when_there_is_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Sending someone to another command mid-flow is the friction we removed."""
        called: dict[str, object] = {}

        monkeypatch.setattr(init, "is_interactive", lambda: True)
        monkeypatch.setattr(init, "list_profiles", lambda: [])
        monkeypatch.setattr(init, "_run_once", lambda _a: 0)
        monkeypatch.setattr(init, "ask_secret", lambda _q: "pk_typed_by_hand")
        monkeypatch.setattr(init, "ask", lambda _q, default=None: "urbs")
        monkeypatch.setattr(init.creds, "ask_provider", lambda: init.ProviderType.CLICKUP)
        monkeypatch.setattr(
            init.creds, "verify_token", lambda p, t: ("dev@example.com", [_team("w1", "One")])
        )
        monkeypatch.setattr(init.creds, "report", lambda *a: None)
        monkeypatch.setattr(
            init.creds,
            "save_profile",
            lambda name, provider, token, ws, **kw: called.update(
                name=name, provider=provider, token=token, ws=ws
            ),
        )

        args = _args()
        assert init.run(args) == 0
        assert called["name"] == "urbs"
        assert called["token"] == "pk_typed_by_hand"
        assert called["ws"] == "w1"
        assert args.profile == "urbs"


def _team(ident: str, name: str):  # type: ignore[no-untyped-def]
    from src.claude_pm.domain.models import Team

    return Team(id=ident, name=name, key=ident)
