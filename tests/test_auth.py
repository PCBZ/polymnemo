import pytest

from polymnemo.auth import AuthError, BearerKeyAuth
from polymnemo.config import Settings


def test_bearer_resolves_user():
    auth = BearerKeyAuth({"k1": "alice", "k2": "bob"})
    assert auth.authenticate({"Authorization": "Bearer k1"}) == "alice"
    # header name is case-insensitive
    assert auth.authenticate({"authorization": "Bearer k2"}) == "bob"


@pytest.mark.parametrize(
    "headers",
    [
        {},  # missing header
        {"Authorization": "Bearer nope"},  # unknown key
        {"Authorization": "k1"},  # no scheme
        {"Authorization": "Basic k1"},  # wrong scheme
        {"Authorization": "Bearer "},  # empty token
    ],
)
def test_bearer_rejects(headers):
    auth = BearerKeyAuth({"k1": "alice"})
    with pytest.raises(AuthError):
        auth.authenticate(headers)


def test_parse_api_keys_drops_malformed():
    s = Settings(api_keys="k1:alice, k2:bob ,,bad, :nouser, keyonly:")
    assert s.parse_api_keys() == {"k1": "alice", "k2": "bob"}
