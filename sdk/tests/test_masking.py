from argus.masking import mask


def test_email():
    out, found = mask("reach me at john.doe+work@example.co.in please")
    assert out == "reach me at <EMAIL> please" and found == ["EMAIL"]


def test_credit_card_luhn_valid():
    out, found = mask("card 4111 1111 1111 1111 charged")
    assert "<CREDIT_CARD>" in out and "CREDIT_CARD" in found


def test_luhn_invalid_number_untouched():
    out, found = mask("order id 4111 1111 1111 1112 shipped")
    assert "4111 1111 1111 1112" in out and found == []


def test_aadhaar_verhoeff():
    valid = "234123412346"  # passes Verhoeff
    out, found = mask(f"aadhaar {valid}")
    assert "<AADHAAR>" in out and "AADHAAR" in found
    out2, found2 = mask("aadhaar 234123412345")
    assert found2 == [] and "234123412345" in out2


def test_ssn_valid_vs_invalid_area():
    assert mask("ssn 123-45-6789")[1] == ["US_SSN"]
    assert mask("ssn 666-45-6789")[1] == []


def test_zip_plus4_not_ssn():
    out, found = mask("mail to 98101-3425, Seattle")
    assert found == [] and "98101-3425" in out


def test_api_keys():
    _, f1 = mask("key sk-ant-api03-" + "a" * 93 + "AA end")
    _, f2 = mask("aws AKIAIOSFODNN7EXAMPLE")
    _, f3 = mask("gh ghp_" + "x" * 36)
    assert f1 == f2 == f3 == ["API_KEY"]


def test_indian_phone():
    out, found = mask("call +91 9876543210 now")
    assert "<PHONE_IN>" in out and found == ["PHONE_IN"]


def test_multiple_entities_and_empty():
    out, found = mask("a@b.com or 9876543210")
    assert found == ["EMAIL", "PHONE_IN"]
    assert mask("")[0] == "" and mask("clean text")[1] == []
