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


_RU_HINTS = {
    5: "токен аккаунта VK недействителен или истёк — получите новый и нажмите «Заменить токен» на странице «Аккаунты VK»",
    6: "слишком много запросов к VK — попробуйте через минуту",
    7: "у токена нет нужных прав — получите токен с правами wall, groups, photos, stats",
    9: "VK ограничил частые однотипные действия (flood control) — попробуйте позже",
    14: "VK требует ввести капчу — зайдите в VK с этого аккаунта в браузере и повторите позже",
    15: "VK запретил это действие для вашего приложения. Создание сообществ доступно только Standalone-приложениям: "
        "создайте группу вручную и выберите «Подключить существующее»",
    27: "это действие требует токен пользователя, а не ключ сообщества",
    100: "VK не принял параметры запроса (проверьте ID сообщества)",
    203: "нет доступа к сообществу — проверьте, что аккаунт администратор",
    214: "публикация на стене сообщества запрещена — проверьте настройки стены и права администратора",
}


def describe_vk_error(exc: Exception) -> str:
    """Human-readable Russian description for UI messages."""
    if isinstance(exc, VKAPIError) and exc.method == "users.get" and "no user" in exc.message:
        return ("Это не токен пользователя (похоже на сервисный или защищённый ключ приложения). "
                "Нужен токен, полученный по ссылке авторизации — см. «Где взять токен»")
    if isinstance(exc, VKAPIError):
        hint = _RU_HINTS.get(exc.code)
        return f"Ошибка VK {exc.code}: {hint}" if hint else f"Ошибка VK {exc.code}: {exc.message}"
    if isinstance(exc, ProxyUnavailableError):
        return "Прокси аккаунта не работает, а свободной замены нет — добавьте живой прокси или отвяжите его"
    if isinstance(exc, VKNetworkError):
        return f"Не удалось связаться с VK ({exc}) — проверьте интернет или прокси"
    return f"Ошибка VK: {exc}"
