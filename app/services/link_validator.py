import re
from urllib.parse import urlparse


SUPPORTED_DOMAINS = {
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "instagram.com",
    "www.instagram.com",
    "tiktok.com",
    "www.tiktok.com",
    "vm.tiktok.com",
}


URL_REGEX = re.compile(
    r"https?://[^\s]+",
    re.IGNORECASE
)


def extract_url(text: str) -> str | None:
    match = URL_REGEX.search(text)
    if not match:
        return None

    return match.group(0).strip()


def normalize_domain(domain: str) -> str:
    return domain.lower().replace("m.", "www.")


def is_supported_public_url(url: str) -> tuple[bool, str]:
    """
    Basic Phase 1 validation.

    Later phases will add:
    - yt-dlp metadata probing
    - private/login-required detection
    - platform-specific rules
    - safe failure handling
    """

    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return False, "Only HTTP and HTTPS links are supported."

    domain = normalize_domain(parsed.netloc)

    if domain not in SUPPORTED_DOMAINS:
        return False, "This platform is not supported yet."

    suspicious_private_markers = [
        "login",
        "signin",
        "accounts",
        "private",
    ]

    lowered_url = url.lower()

    for marker in suspicious_private_markers:
        if marker in lowered_url:
            return False, "This link looks private or login-protected, so I cannot process it."

    return True, "Supported public-looking link."