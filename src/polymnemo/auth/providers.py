"""The identity providers a human can sign in with on the token page.

Each provider is a separate identity. A GitHub login and a Google login are
different users with separate memory, on purpose (#153): one person may keep a
personal account and a work account, and those should not see each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings


@dataclass(frozen=True)
class IdentityProvider:
    key: str
    label: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str
    # Where the stable account id lives in the userinfo response. Never an
    # email: addresses change hands, and the next holder would inherit the
    # previous one's memory.
    subject_field: str
    # Something the account holder recognises, shown on the token page so two
    # accounts are told apart by sight. Display only -- never the identity key,
    # because an email can be reassigned and the next holder would inherit the
    # previous one's memory.
    display_field: str
    # Settings attributes rather than values, so a test can set credentials
    # after this table is built.
    client_id_setting: str
    client_secret_setting: str
    userinfo_headers: dict[str, str] = field(default_factory=dict)

    @property
    def subject_prefix(self) -> str:
        return f"{self.key}:"

    @property
    def client_id(self) -> str:
        return getattr(settings, self.client_id_setting)

    @property
    def client_secret(self) -> str:
        return getattr(settings, self.client_secret_setting)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


GITHUB = IdentityProvider(
    key="github",
    label="GitHub",
    authorize_url="https://github.com/login/oauth/authorize",
    token_url="https://github.com/login/oauth/access_token",
    userinfo_url="https://api.github.com/user",
    scope="read:user",
    subject_field="id",
    display_field="login",
    client_id_setting="oauth_client_id",
    client_secret_setting="oauth_client_secret",
    userinfo_headers={"Accept": "application/vnd.github+json"},
)

GOOGLE = IdentityProvider(
    key="google",
    label="Google",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
    scope="openid email profile",
    subject_field="sub",
    display_field="email",
    client_id_setting="google_client_id",
    client_secret_setting="google_client_secret",
)

PROVIDERS: dict[str, IdentityProvider] = {p.key: p for p in (GITHUB, GOOGLE)}


def enabled() -> list[IdentityProvider]:
    """Providers this deployment has credentials for, in a stable order."""
    return [p for p in PROVIDERS.values() if p.configured]


def get(key: str) -> IdentityProvider | None:
    """Look up a provider by key, but only if it is configured — so a crafted
    URL cannot start a flow against a provider the operator never enabled."""
    provider = PROVIDERS.get(key)
    return provider if provider is not None and provider.configured else None
