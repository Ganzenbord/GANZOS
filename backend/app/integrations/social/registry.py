"""Welke social-platforms Ganz kent."""

from __future__ import annotations

from app.integrations.base import SocialProvider
from app.integrations.social.instagram import InstagramProvider
from app.integrations.social.tiktok import TikTokProvider
from app.integrations.social.youtube import YouTubeProvider

_PROVIDERS: dict[str, SocialProvider] = {
    provider.platform: provider
    for provider in (YouTubeProvider(), InstagramProvider(), TikTokProvider())
}


def get_social_provider(platform: str) -> SocialProvider | None:
    return _PROVIDERS.get(platform)


def social_platform_keys() -> list[str]:
    return sorted(_PROVIDERS)


def describe_social_providers() -> list[dict[str, str]]:
    return [
        {"platform": p.platform, "display_name": p.display_name}
        for p in sorted(_PROVIDERS.values(), key=lambda p: p.platform)
    ]


def register_social_provider(provider: SocialProvider) -> None:
    """Haakje voor tests en voor een platform dat later wordt bijgeplugd."""
    _PROVIDERS[provider.platform] = provider
