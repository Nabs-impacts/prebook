from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib.parse import ParseResult, parse_qs, urlparse

import httpx

from app.core.errors import BadRequestError, ServiceUnavailableError
from app.models.enums import VideoStatus

CLOUDFLARE_API_BASE_URL = "https://api.cloudflare.com/client/v4"
CLOUDFLARE_EMBED_URL = "https://iframe.videodelivery.net/{video_id}"
YOUTUBE_EMBED_URL = "https://www.youtube.com/embed/{video_id}"
VIMEO_EMBED_URL = "https://player.vimeo.com/video/{video_id}"
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtu.be",
}
VIMEO_HOSTS = {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}
YOUTUBE_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


@dataclass(frozen=True, slots=True)
class DirectUpload:
    upload_url: str
    provider_video_id: str


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    status: VideoStatus
    duration_seconds: int | None = None
    thumbnail_url: str | None = None
    hls_url: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalVideo:
    provider_video_id: str
    embed_url: str


class VideoProvider(ABC):
    @abstractmethod
    async def create_direct_upload(
        self,
        max_duration_seconds: int,
        max_size_bytes: int,
    ) -> DirectUpload: ...

    @abstractmethod
    async def fetch_metadata(self, provider_video_id: str) -> VideoMetadata: ...

    @abstractmethod
    async def delete(self, provider_video_id: str) -> None: ...

    @abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> VideoMetadata: ...


class ExternalUrlProvider(VideoProvider):
    async def create_direct_upload(
        self,
        max_duration_seconds: int,
        max_size_bytes: int,
    ) -> DirectUpload:
        raise BadRequestError("Une vidéo externe ne prend pas en charge l'upload direct.")

    async def fetch_metadata(self, provider_video_id: str) -> VideoMetadata:
        return VideoMetadata(status=VideoStatus.READY)

    async def delete(self, provider_video_id: str) -> None:
        return None

    def parse_webhook(self, payload: dict[str, Any]) -> VideoMetadata:
        raise BadRequestError("Une vidéo externe ne reçoit pas de webhook.")

    def parse(self, url: str) -> ExternalVideo:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise BadRequestError("L'URL de la vidéo est invalide.")
        host = parsed.netloc.lower().split(":")[0]
        if host in YOUTUBE_HOSTS:
            return self._parse_youtube(parsed)
        if host in VIMEO_HOSTS:
            return self._parse_vimeo(parsed)
        raise BadRequestError("Seules les vidéos YouTube et Vimeo sont prises en charge.")

    def embed_url(self, url: str) -> str:
        return self.parse(url).embed_url

    def _parse_youtube(self, parsed: ParseResult) -> ExternalVideo:
        if parsed.netloc.lower().split(":")[0] == "youtu.be":
            video_id = parsed.path.strip("/").split("/")[0]
        elif parsed.path.startswith("/watch"):
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            segments = [segment for segment in parsed.path.split("/") if segment]
            video_id = segments[1] if len(segments) >= 2 else ""
        self._validate_youtube_id(video_id)
        return ExternalVideo(
            provider_video_id=video_id,
            embed_url=YOUTUBE_EMBED_URL.format(video_id=video_id),
        )

    def _parse_vimeo(self, parsed: ParseResult) -> ExternalVideo:
        segments = [segment for segment in parsed.path.split("/") if segment]
        video_id = segments[0] if segments else ""
        if not video_id.isdigit():
            raise BadRequestError("L'identifiant Vimeo est invalide.")
        return ExternalVideo(
            provider_video_id=video_id,
            embed_url=VIMEO_EMBED_URL.format(video_id=video_id),
        )

    def _validate_youtube_id(self, video_id: str) -> None:
        if len(video_id) < 6 or len(video_id) > 64 or not set(video_id) <= YOUTUBE_ID_CHARS:
            raise BadRequestError("L'identifiant YouTube est invalide.")


class CloudflareStreamProvider(VideoProvider):
    def __init__(
        self,
        account_id: str,
        api_token: str,
        base_url: str = CLOUDFLARE_API_BASE_URL,
    ) -> None:
        self._account_id = account_id
        self._api_token = api_token
        self._base_url = base_url.rstrip("/")

    def _ensure_configured(self) -> None:
        if not self._account_id or not self._api_token:
            raise ServiceUnavailableError("Cloudflare Stream n'est pas configuré.")

    def _url(self, path: str) -> str:
        return f"{self._base_url}/accounts/{self._account_id}/stream{path}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_token}"}

    async def create_direct_upload(
        self,
        max_duration_seconds: int,
        max_size_bytes: int,
    ) -> DirectUpload:
        self._ensure_configured()
        payload = {
            "maxDurationSeconds": max_duration_seconds,
            "maxSizeBytes": max_size_bytes,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self._url("/direct_upload"),
                headers=self._headers(),
                json=payload,
            )
        result = self._result(response)
        upload_url = result.get("uploadURL")
        video_id = result.get("uid")
        if not isinstance(upload_url, str) or not isinstance(video_id, str):
            raise ServiceUnavailableError("Réponse Cloudflare Stream invalide.")
        return DirectUpload(upload_url=upload_url, provider_video_id=video_id)

    async def fetch_metadata(self, provider_video_id: str) -> VideoMetadata:
        self._ensure_configured()
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                self._url(f"/{provider_video_id}"),
                headers=self._headers(),
            )
        return self._metadata(self._result(response))

    async def delete(self, provider_video_id: str) -> None:
        self._ensure_configured()
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.delete(
                self._url(f"/{provider_video_id}"),
                headers=self._headers(),
            )
        if response.status_code not in (200, 204, 404):
            raise ServiceUnavailableError("Suppression Cloudflare Stream impossible.")

    def parse_webhook(self, payload: dict[str, Any]) -> VideoMetadata:
        return self._metadata(payload)

    def _result(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise ServiceUnavailableError("Cloudflare Stream est indisponible.")
        try:
            body = response.json()
        except ValueError as error:
            raise ServiceUnavailableError("Réponse Cloudflare Stream invalide.") from error
        if not isinstance(body, dict) or not body.get("success", False):
            raise ServiceUnavailableError("Réponse Cloudflare Stream invalide.")
        result = body.get("result")
        if not isinstance(result, dict):
            raise ServiceUnavailableError("Réponse Cloudflare Stream invalide.")
        return result

    def _metadata(self, result: dict[str, Any]) -> VideoMetadata:
        status_payload = result.get("status")
        state = ""
        if isinstance(status_payload, dict):
            raw_state = status_payload.get("state")
            if isinstance(raw_state, str):
                state = raw_state
        ready = result.get("readyToStream") is True
        if state == "ready" or (ready and state != "error"):
            status = VideoStatus.READY
        elif state == "error":
            status = VideoStatus.FAILED
        else:
            status = VideoStatus.PROCESSING
        return VideoMetadata(
            status=status,
            duration_seconds=self._duration(result.get("duration")),
            thumbnail_url=self._text(result.get("thumbnail")),
            hls_url=self._hls_url(result.get("playback")),
        )

    def _duration(self, value: Any) -> int | None:
        if isinstance(value, (int, float)):
            return round(float(value))
        return None

    def _text(self, value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    def _hls_url(self, playback: Any) -> str | None:
        if isinstance(playback, dict):
            return self._text(playback.get("hls"))
        return None


def cloudflare_embed_url(video_id: str) -> str:
    return CLOUDFLARE_EMBED_URL.format(video_id=video_id)
