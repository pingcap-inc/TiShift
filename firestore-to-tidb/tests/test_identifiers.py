"""Tests for SQL identifier validation and quoting."""

from __future__ import annotations

import pytest

from tishift_firestore.rules.identifiers import (
    UnsafeIdentifierError,
    is_safe_ident,
    quote_ident,
    safe_column_name,
    safe_table_name,
)


# ---- quote_ident -----------------------------------------------------------

def test_quote_ident_simple():
    assert quote_ident("users") == "`users`"


def test_quote_ident_escapes_backtick():
    # MySQL quoting rule: double the backtick
    assert quote_ident("foo`bar") == "`foo``bar`"


def test_quote_ident_rejects_nul():
    with pytest.raises(UnsafeIdentifierError):
        quote_ident("foo\x00bar")


def test_quote_ident_rejects_control_chars():
    with pytest.raises(UnsafeIdentifierError):
        quote_ident("foo\nbar")
    with pytest.raises(UnsafeIdentifierError):
        quote_ident("foo\tbar")


def test_quote_ident_rejects_empty():
    with pytest.raises(UnsafeIdentifierError):
        quote_ident("")


def test_quote_ident_rejects_oversize():
    with pytest.raises(UnsafeIdentifierError):
        quote_ident("a" * 65)


# ---- is_safe_ident ---------------------------------------------------------

def test_is_safe_ident_accepts_plain():
    assert is_safe_ident("users")
    assert is_safe_ident("user_orders")
    assert is_safe_ident("u123")


def test_is_safe_ident_rejects_leading_digit():
    assert not is_safe_ident("1abc")


def test_is_safe_ident_rejects_specials():
    assert not is_safe_ident("user-orders")
    assert not is_safe_ident("user`orders")
    assert not is_safe_ident("user orders")
    assert not is_safe_ident("user;DROP TABLE x;--")


# ---- safe_table_name -------------------------------------------------------

def test_safe_table_name_root():
    assert safe_table_name("users") == "users"


def test_safe_table_name_subcollection_drops_id():
    # users / {uid} / orders → users_orders
    assert safe_table_name("users/abc123/orders") == "users_orders"


def test_safe_table_name_rejects_injection():
    with pytest.raises(UnsafeIdentifierError):
        safe_table_name("users`; DROP TABLE x; --")
    with pytest.raises(UnsafeIdentifierError):
        safe_table_name("users\x00")


def test_safe_table_name_rejects_too_long():
    with pytest.raises(UnsafeIdentifierError):
        safe_table_name("a" * 70)


# ---- safe_column_name ------------------------------------------------------

def test_safe_column_name_simple():
    assert safe_column_name("email") == "email"


def test_safe_column_name_dotted():
    assert safe_column_name("address.city") == "address_city"


def test_safe_column_name_rejects_unsafe():
    with pytest.raises(UnsafeIdentifierError):
        safe_column_name("foo`bar")
    with pytest.raises(UnsafeIdentifierError):
        safe_column_name("foo;DROP")
