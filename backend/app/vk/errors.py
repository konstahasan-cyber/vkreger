from __future__ import annotations

# https://dev.vk.com/ru/reference/errors
AUTH_ERRORS = {5}  # user authorization failed (token invalid / expired / revoked)
CAPTCHA_ERRORS = {14}
FLOOD_ERRORS = {9}  # flood control: too many similar actions
RATE_ERRORS = {6}  # too many requests per second
RETRYABLE_ERRORS = {1, 6, 10}  # unknown / rate / internal server error
PERMISSION_ERRORS = {7, 15, 27, 203, 214}  # 214 = access to adding post denied
VALIDATION_ERRORS = {100, 113}


class VKError(Exception):
    """Base error for everything related to VK interaction."""

    retryable = False


class VKNetworkError(VKError):
    retryable = True


class ProxyUnavailableError(VKError):
    """The account's proxy is dead and no replacement is available.

    We intentionally do *not* fall back to a direct connection.
    """


class VKAPIError(VKError):
    def __init__(self, code: int, message: str, method: str | None = None, extra: dict | None = None):
        super().__init__(f"VK API error {code} in {method}: {message}")
        self.code = code
        self.message = message
        self.method = method
        self.extra = extra or {}

    @property
    def is_auth(self) -> bool:
        return self.code in AUTH_ERRORS

    @property
    def is_captcha(self) -> bool:
        return self.code in CAPTCHA_ERRORS

    @property
    def is_flood(self) -> bool:
        return self.code in FLOOD_ERRORS

    @property
    def is_permission(self) -> bool:
        return self.code in PERMISSION_ERRORS

    @property
    def retryable(self) -> bool:  # type: ignore[override]
        return self.code in RETRYABLE_ERRORS
