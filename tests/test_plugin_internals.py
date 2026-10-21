"""The plugin internals, called directly rather than through a subprocess.

`tests/test_scanners.py` drives these through the real RSP runtime, which is
what proves the wiring. It is also slow, invisible to coverage, and tells you
only that *something* in a child process disagreed. These are pure functions;
calling them gives a precise failure and costs nothing.
"""

from __future__ import annotations

import json

import pytest

from polymnemo.plugins import _runner, _strictjson, tokens

TOKEN = b"pmn_" + b"AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"


class TestTokenDetection:
    def test_a_token_blocks(self):
        assert tokens.inspect(b"my key is " + TOKEN)["verdict"] == "BLOCK"

    def test_the_count_is_reported(self):
        out = tokens.inspect(TOKEN + b" and " + TOKEN)
        assert "2" in out["reason"]

    @pytest.mark.parametrize(
        "text",
        [
            b"I prefer dark roast coffee",
            b"pmn_ is the prefix we use",  # the prefix alone is not a token
            b"pmn_short",  # below the length floor
            "我喜欢深烘咖啡".encode(),
            b"",
        ],
    )
    def test_ordinary_text_passes(self, text):
        assert tokens.inspect(text)["verdict"] == "ALLOW"

    def test_an_allow_carries_nothing_else(self):
        """V2: the common case is the cheap one."""
        assert tokens.inspect(b"ordinary") == {"verdict": "ALLOW"}

    def test_the_declaration_has_what_the_handshake_needs(self):
        """H2: absent or wrongly typed and the host refuses the plugin."""
        d = tokens.declare()
        assert all(isinstance(d[k], str) for k in ("rsp_version", "name", "version"))
        assert isinstance(d["hooks"], list)
        assert all(isinstance(h, str) for h in d["hooks"])
        assert isinstance(d["deterministic"], bool)


class TestStrictJson:
    """T4's leniencies, each of which a plain `json.loads` would accept. These
    are the two that a partial copy of this file got wrong (#164)."""

    def test_an_integer_above_the_safe_range_is_refused(self):
        with pytest.raises(ValueError):
            _strictjson.loads(json.dumps({"n": 2**53}))

    def test_the_safe_range_includes_its_edges(self):
        assert _strictjson.loads(json.dumps({"n": 2**53 - 1}))["n"] == 2**53 - 1

    def test_an_unpaired_surrogate_is_refused(self):
        with pytest.raises(ValueError):
            _strictjson.loads('{"k": "\\ud800"}')

    def test_an_unpaired_surrogate_in_a_key_is_refused(self):
        with pytest.raises(ValueError):
            _strictjson.loads('{"\\ud800": "v"}')

    def test_a_repeated_key_is_refused(self):
        with pytest.raises(ValueError, match="repeated key"):
            _strictjson.loads('{"a": 1, "a": 2}')

    def test_sibling_objects_may_repeat_a_key(self):
        assert _strictjson.loads('{"x": {"a": 1}, "y": {"a": 2}}')["y"]["a"] == 2

    @pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
    def test_the_javascript_constants_are_not_numbers(self, token):
        with pytest.raises(ValueError):
            _strictjson.loads('{"n": %s}' % token)

    @pytest.mark.parametrize("pad", ["\x0b", "\x0c"])
    def test_python_whitespace_is_not_json_whitespace(self, pad):
        """Vertical tab and form feed satisfy `str.isspace()` and are not JSON
        whitespace, which is the gap the framing check closes. A BOM never
        reaches it: Python does not call that whitespace either, so `json`
        rejects it first."""
        with pytest.raises(ValueError, match="framed by"):
            _strictjson.loads(pad + '{"a": 1}')

    def test_a_byte_order_mark_is_still_refused(self):
        with pytest.raises(ValueError):
            _strictjson.loads("\ufeff" + '{"a": 1}')

    def test_booleans_pass_the_range_check(self):
        """A bool is an int in Python; checking its magnitude would be wrong."""
        assert _strictjson.loads('{"a": true}')["a"] is True

    def test_values_inside_lists_are_checked(self):
        assert _strictjson.loads('{"a": [1, 2]}')["a"] == [1, 2]
        with pytest.raises(ValueError):
            _strictjson.loads('{"a": [1, %d]}' % 2**53)

    def test_ordinary_framing_is_accepted(self):
        assert _strictjson.loads(' \t\n\r{"a": 1}\n ')["a"] == 1


class TestRunner:
    def _drive(self, request: str, monkeypatch, capsysbinary):
        class _In:
            buffer = type("B", (), {"read": staticmethod(lambda: request.encode())})()

        monkeypatch.setattr(_runner.sys, "stdin", _In)
        _runner.run(tokens.declare, tokens.inspect)
        return capsysbinary.readouterr()

    def test_a_handshake_returns_the_declaration(self, monkeypatch, capsysbinary):
        out = self._drive('{"hook": "handshake"}', monkeypatch, capsysbinary)
        assert json.loads(out.out)["name"] == "polymnemo-tokens"

    def test_a_chunk_is_judged(self, monkeypatch, capsysbinary):
        body = json.dumps({"hook": "on_chunk", "content": TOKEN.decode()})
        out = self._drive(body, monkeypatch, capsysbinary)
        assert json.loads(out.out)["verdict"] == "BLOCK"

    def test_the_response_is_one_line_of_utf8(self, monkeypatch, capsysbinary):
        body = json.dumps({"hook": "on_chunk", "content": "咖啡"})
        out = self._drive(body, monkeypatch, capsysbinary)
        assert out.out.endswith(b"\n")
        assert out.out.count(b"\n") == 1

    def test_a_malformed_request_exits_nonzero_with_nothing_on_stdout(
        self, monkeypatch, capsysbinary
    ):
        """T2: a stray line on stdout is indistinguishable from a response."""
        with pytest.raises(SystemExit):
            self._drive('{"a": 1, "a": 2}', monkeypatch, capsysbinary)
        out = capsysbinary.readouterr()
        assert out.out == b""
        assert b"polymnemo-tokens" in out.err
