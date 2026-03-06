"""Tests for cursor pagination encoding/decoding and has_more."""

from __future__ import annotations

import pytest

from tlgr.core.output import encode_cursor, decode_cursor, add_pagination


class TestCursorEncoding:
    def test_roundtrip(self):
        state = {"offset_id": 12345}
        token = encode_cursor(state)
        assert isinstance(token, str)
        assert len(token) > 0
        decoded = decode_cursor(token)
        assert decoded == state

    def test_roundtrip_complex(self):
        state = {"offset": 50, "offset_id": 999}
        token = encode_cursor(state)
        decoded = decode_cursor(token)
        assert decoded == state

    def test_decode_none(self):
        assert decode_cursor(None) == {}

    def test_decode_empty(self):
        assert decode_cursor("") == {}

    def test_decode_invalid(self):
        assert decode_cursor("not-valid-base64!!!") == {}

    def test_decode_corrupt_json(self):
        import base64
        token = base64.urlsafe_b64encode(b"not json").decode().rstrip("=")
        assert decode_cursor(token) == {}


class TestAddPagination:
    def test_has_more_true(self):
        envelope: dict = {"messages": [1, 2, 3]}
        result = add_pagination(envelope, [1, 2, 3], limit=3, cursor_state={"offset_id": 100})
        assert result["has_more"] is True
        assert "next_cursor" in result
        decoded = decode_cursor(result["next_cursor"])
        assert decoded == {"offset_id": 100}

    def test_has_more_false(self):
        envelope: dict = {"messages": [1, 2]}
        result = add_pagination(envelope, [1, 2], limit=5, cursor_state={"offset_id": 100})
        assert result["has_more"] is False
        assert "next_cursor" not in result

    def test_empty_results(self):
        envelope: dict = {"messages": []}
        result = add_pagination(envelope, [], limit=10, cursor_state={})
        assert result["has_more"] is False

    def test_exact_limit(self):
        items = list(range(20))
        envelope: dict = {"items": items}
        result = add_pagination(envelope, items, limit=20, cursor_state={"offset": 20})
        assert result["has_more"] is True
