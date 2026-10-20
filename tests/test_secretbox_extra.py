import pytest
import sys
import os

# Add the backend directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

# Assuming secretbox module contains seal and open_
import secretbox

def test_same_text_twice_gives_different_tokens(monkeypatch):
    """Test that sealing the same text twice produces different tokens."""
    # Ensure a unique nonce is used for each call
    text = "some sensitive data"
    token1 = secretbox.seal(text)
    token2 = secretbox.seal(text)
    assert token1 != token2

def test_roundtrip_reversibility(monkeypatch):
    """Test open_(seal(x)) == x for Unicode and long strings."""
    # Unicode test
    unicode_text = "Привет, world! This is a test of Unicode characters and complex symbols like € and ™."
    token_unicode = secretbox.seal(unicode_text)
    assert secretbox.open_(token_unicode) == unicode_text

    # Long string test (200 characters)
    long_text = "A" * 200
    token_long = secretbox.seal(long_text)
    assert secretbox.open_(token_long) == long_text

def test_base64_manipulation_raises_error(monkeypatch):
    """Flipping any one character of the sealed part fails the integrity check."""
    monkeypatch.setenv("DXMAP_ENV", "dev")
    token = secretbox.seal("test_base64_manipulation")
    body = token[3:]
    for i in (0, len(body) // 2, len(body) - 6):
        flipped = "B" if body[i] == "A" else "A"
        with pytest.raises(ValueError):
            secretbox.open_("v1:" + body[:i] + flipped + body[i + 1:])


def test_cross_token_failure(monkeypatch):
    """Test that a token sealed under one service token fails to open under another."""
    # Setup environment for the test
    
    # 1. Seal a token using 'a'
    monkeypatch.setenv("DXMAP_SERVICE_TOKEN", "token_a_secure_service_token")
    monkeypatch.setenv("DXMAP_ENV", "dev")
    
    try:
        original_token = secretbox.seal("secret_data_for_test")
    except Exception as e:
        pytest.fail(f"Failed to seal token with token 'a': {e}")

    # 2. Change the environment to use 'b'
    monkeypatch.setenv("DXMAP_SERVICE_TOKEN", "token_b_another_service_token")
    
    # 3. Attempt to open the token sealed by 'a' using 'b'
    # This MUST raise an error related to token mismatch or initialization failure.
    with pytest.raises(ValueError):
        secretbox.open_(original_token)
