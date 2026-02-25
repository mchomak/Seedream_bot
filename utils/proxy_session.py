# proxy_session.py
"""
Custom Telegram session that supports selective proxy routing.

Three modes are configured via TELEGRAM_PROXY_MODE in .env:
  none  – proxy is only used for the AI (Seedream) API, Telegram goes direct
  media – file uploads/downloads go through proxy, lightweight API calls go direct
  full  – all Telegram traffic goes through proxy
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, Optional

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType

if TYPE_CHECKING:
    from aiogram import Bot

# Telegram API methods that transfer binary file data (uploads).
# These are the calls that get throttled by ISPs when media traffic is blocked.
_MEDIA_METHODS = frozenset({
    "SendPhoto",
    "SendDocument",
    "SendVideo",
    "SendAnimation",
    "SendAudio",
    "SendVoice",
    "SendVideoNote",
    "SendSticker",
    "SendMediaGroup",
    "SetChatPhoto",
    "UploadStickerFile",
    "CreateNewStickerSet",
    "AddStickerToSet",
    "SetStickerSetThumbnail",
})


class MediaProxySession(AiohttpSession):
    """
    Telegram session that routes file upload/download API calls through a
    proxy while sending all other (lightweight) API calls directly.

    Useful when the ISP throttles Telegram media traffic but not general
    API traffic (e.g. getUpdates, sendMessage, answerCallbackQuery, …).
    """

    def __init__(self, media_proxy: str, timeout: int = 300) -> None:
        # Parent session = direct path (no proxy) for regular API calls
        super().__init__(timeout=timeout)
        # Separate session for all media (upload / download) traffic
        self._media = AiohttpSession(proxy=media_proxy, timeout=timeout)

    async def make_request(
        self,
        bot: "Bot",
        method: TelegramMethod[TelegramType],
        timeout: Optional[int] = None,
    ) -> TelegramType:
        if type(method).__name__ in _MEDIA_METHODS:
            return await self._media.make_request(bot, method, timeout)
        return await super().make_request(bot, method, timeout)

    async def stream_content(
        self,
        url: str,
        headers: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        # bot.download() uses stream_content — route through proxy too
        async for chunk in self._media.stream_content(
            url,
            headers=headers,
            timeout=timeout,
            chunk_size=chunk_size,
            raise_for_status=raise_for_status,
        ):
            yield chunk

    async def close(self) -> None:
        await super().close()
        await self._media.close()


def build_telegram_session(
    proxy: Optional[str],
    mode: str,
    timeout: int = 300,
) -> AiohttpSession:
    """
    Factory that creates the appropriate Telegram session.

    Args:
        proxy: Proxy URL, e.g. ``socks5://user:pass@host:1080`` or
               ``http://host:3128``.  Requires ``aiohttp-socks`` for SOCKS.
        mode:  One of:
               ``"none"``  – no proxy for Telegram (proxy used only for AI API)
               ``"media"`` – proxy only for file uploads/downloads
               ``"full"``  – proxy for all Telegram API calls
        timeout: Session timeout in seconds (default 300).
    """
    mode = (mode or "none").lower().strip()

    if mode == "full" and proxy:
        return AiohttpSession(proxy=proxy, timeout=timeout)

    if mode == "media" and proxy:
        return MediaProxySession(media_proxy=proxy, timeout=timeout)

    # mode == "none" or no proxy configured
    return AiohttpSession(timeout=timeout)
