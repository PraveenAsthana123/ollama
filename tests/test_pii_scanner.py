import scripts.pii_scanner as pii_scanner


def test_flags_email():
    assert pii_scanner.scan("Contact me at jane.doe@example.com")["types"] == ["email"]


def test_flags_ssn():
    assert pii_scanner.scan("My SSN is 123-45-6789")["types"] == ["ssn"]


def test_flags_phone():
    assert pii_scanner.scan("Call me at 555-123-4567")["types"] == ["phone"]


def test_flags_luhn_valid_card_number():
    # 4532015112830366 is a well-known public Luhn-valid test number, not a real card
    result = pii_scanner.scan("My card number is 4532015112830366")
    assert "credit_card" in result["types"]


def test_does_not_flag_luhn_invalid_digit_sequence():
    # Same length as a card number, but fails the Luhn checksum -- a naive
    # shape-only regex would false-positive here; the checksum should not
    result = pii_scanner.scan("Order ID: 1234567890123456")
    assert "credit_card" not in result["types"]


def test_does_not_flag_legitimate_text():
    result = pii_scanner.scan("What is the capital of France?")
    assert result["flagged"] is False
    assert result["types"] == []


def test_does_not_flag_a_bare_undelimited_ten_digit_number_as_phone():
    # Real bug found and fixed 2026-09-21: the first phone regex had every
    # separator optional, so a plain 10-digit multiplication answer
    # (84213 * 61970 = 5218679610) false-positived as a phone number.
    result = pii_scanner.scan("What is 84213 times 61970?\n5218679610")
    assert "phone" not in result["types"]


def test_flags_phone_with_parens_and_space():
    assert "phone" in pii_scanner.scan("Contact: (555) 123-4567")["types"]


def test_flags_phone_with_dots():
    assert "phone" in pii_scanner.scan("Phone: 555.123.4567")["types"]


def test_flagged_is_false_when_types_empty():
    assert pii_scanner.scan("nothing sensitive here")["flagged"] is False
