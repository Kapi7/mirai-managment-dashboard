"""
TikTok Content Posting API Integration

Provides video and photo publishing to TikTok via the Content Posting API v2.
Same interface pattern as the Instagram publisher used elsewhere in the codebase.

API reference: https://developers.tiktok.com/doc/content-posting-api-reference
Base URL:      https://open.tiktokapis.com/v2

Authentication:
    Requires a valid TikTok access token (OAuth 2.0) stored in the
    TIKTOK_ACCESS_TOKEN environment variable.  Scopes needed:
        - video.publish
        - video.upload
        - user.info.basic
        - video.list
"""

import os
import json
import base64
import asyncio
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict, field

import httpx


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"

# Content Posting API endpoints
CREATOR_INFO_URL = f"{TIKTOK_API_BASE}/post/publish/creator_info/query/"
INIT_VIDEO_URL = f"{TIKTOK_API_BASE}/post/publish/video/init/"
INIT_PHOTO_URL = f"{TIKTOK_API_BASE}/post/publish/content/init/"
PUBLISH_STATUS_URL = f"{TIKTOK_API_BASE}/post/publish/status/fetch/"

# User info endpoint
USER_INFO_URL = f"{TIKTOK_API_BASE}/user/info/"

# Video list / insights
VIDEO_LIST_URL = f"{TIKTOK_API_BASE}/video/list/"
VIDEO_QUERY_URL = f"{TIKTOK_API_BASE}/video/query/"

# Upload constraints
MAX_VIDEO_SIZE_BYTES = 4 * 1024 * 1024 * 1024   # 4 GB
MAX_PHOTO_SIZE_BYTES = 20 * 1024 * 1024          # 20 MB
MAX_CAPTION_LENGTH = 2200
MAX_HASHTAGS = 30
CHUNK_SIZE_BYTES = 10 * 1024 * 1024              # 10 MB chunks for large uploads

# Polling
PUBLISH_POLL_INTERVAL_SEC = 3
PUBLISH_POLL_MAX_ATTEMPTS = 60  # 3 minutes max


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TikTokPostResult:
    """Result from a publish operation."""
    success: bool = False
    publish_id: str = ""
    post_id: str = ""
    status: str = ""
    error_code: str = ""
    error_message: str = ""
    created_at: str = ""


@dataclass
class TikTokPostInsights:
    """Engagement metrics for a TikTok post."""
    post_id: str = ""
    title: str = ""
    create_time: int = 0
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    duration: int = 0
    cover_image_url: str = ""
    embed_link: str = ""
    video_description: str = ""


@dataclass
class TikTokAccountInfo:
    """TikTok account profile information."""
    open_id: str = ""
    union_id: str = ""
    display_name: str = ""
    avatar_url: str = ""
    avatar_url_100: str = ""
    bio_description: str = ""
    profile_deep_link: str = ""
    is_verified: bool = False
    follower_count: int = 0
    following_count: int = 0
    likes_count: int = 0
    video_count: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_caption(caption: str, hashtags: Optional[List[str]] = None) -> str:
    """
    Build the final post caption with hashtags appended.

    TikTok expects hashtags inline in the caption text (not as separate
    fields like Instagram).  We append them at the end.
    """
    parts = [caption.strip()] if caption else []

    if hashtags:
        tags = []
        for tag in hashtags[:MAX_HASHTAGS]:
            tag = tag.strip().lstrip("#")
            if tag:
                tags.append(f"#{tag}")
        if tags:
            parts.append(" ".join(tags))

    full_caption = "\n\n".join(parts)
    return full_caption[:MAX_CAPTION_LENGTH]


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# TikTokPublisher
# ---------------------------------------------------------------------------

class TikTokPublisher:
    """
    TikTok Content Posting API v2 integration.

    Usage:
        publisher = TikTokPublisher()
        result = await publisher.upload_video(video_b64, "Check this out!", ["skincare", "beauty"])
        insights = await publisher.get_post_insights(result.post_id)
    """

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token or os.getenv("TIKTOK_ACCESS_TOKEN", "")
        if not self.access_token:
            raise ValueError(
                "TikTok access token is required. Set TIKTOK_ACCESS_TOKEN env var "
                "or pass access_token to __init__."
            )
        self._http_timeout = 120  # seconds

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self, content_type: str = "application/json") -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": content_type,
        }

    async def _request(
        self,
        method: str,
        url: str,
        json_body: Optional[dict] = None,
        data: Optional[bytes] = None,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> dict:
        """Execute an HTTP request and return parsed JSON."""
        hdrs = headers or self._headers()
        async with httpx.AsyncClient(timeout=timeout or self._http_timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=hdrs,
                json=json_body,
                content=data,
                params=params,
            )

            # TikTok API may return 200 with error in body
            try:
                result = response.json()
            except Exception:
                result = {
                    "error": {
                        "code": f"http_{response.status_code}",
                        "message": response.text[:500],
                    }
                }

            # Raise for non-2xx only if there is no structured error we can read
            if response.status_code >= 400 and "error" not in result:
                response.raise_for_status()

            return result

    # ------------------------------------------------------------------
    # Video upload
    # ------------------------------------------------------------------

    async def upload_video(
        self,
        video_data_b64: str,
        caption: str = "",
        hashtags: Optional[List[str]] = None,
        privacy_level: str = "PUBLIC_TO_EVERYONE",
        disable_duet: bool = False,
        disable_stitch: bool = False,
        disable_comment: bool = False,
        video_cover_timestamp_ms: int = 1000,
    ) -> TikTokPostResult:
        """
        Upload a video to TikTok.

        Args:
            video_data_b64:  Base64-encoded video file bytes.
            caption:         Post caption / description.
            hashtags:        List of hashtag strings (without #).
            privacy_level:   PUBLIC_TO_EVERYONE | MUTUAL_FOLLOW_FRIENDS |
                             FOLLOWER_OF_CREATOR | SELF_ONLY
            disable_duet:    Disable duet on this video.
            disable_stitch:  Disable stitch on this video.
            disable_comment: Disable comments on this video.
            video_cover_timestamp_ms: Timestamp in ms for auto cover image.

        Returns:
            TikTokPostResult with publish_id and eventually post_id.
        """
        # Decode the base64 video
        try:
            video_bytes = base64.b64decode(video_data_b64)
        except Exception as e:
            return TikTokPostResult(
                success=False,
                error_code="decode_error",
                error_message=f"Failed to decode base64 video data: {e}",
            )

        video_size = len(video_bytes)
        if video_size > MAX_VIDEO_SIZE_BYTES:
            return TikTokPostResult(
                success=False,
                error_code="file_too_large",
                error_message=f"Video size {video_size} bytes exceeds maximum {MAX_VIDEO_SIZE_BYTES}.",
            )

        full_caption = _build_caption(caption, hashtags)

        # Step 1: Initialize the upload via Content Posting API
        if video_size > CHUNK_SIZE_BYTES:
            # Chunked upload for large files
            return await self._chunked_video_upload(
                video_bytes=video_bytes,
                caption=full_caption,
                privacy_level=privacy_level,
                disable_duet=disable_duet,
                disable_stitch=disable_stitch,
                disable_comment=disable_comment,
                video_cover_timestamp_ms=video_cover_timestamp_ms,
            )

        # Direct upload for smaller files
        init_body = {
            "post_info": {
                "title": full_caption,
                "privacy_level": privacy_level,
                "disable_duet": disable_duet,
                "disable_stitch": disable_stitch,
                "disable_comment": disable_comment,
                "video_cover_timestamp_ms": video_cover_timestamp_ms,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": video_size,
                "total_chunk_count": 1,
            },
        }

        init_resp = await self._request("POST", INIT_VIDEO_URL, json_body=init_body)

        error = init_resp.get("error", {})
        if error.get("code") and error["code"] != "ok":
            return TikTokPostResult(
                success=False,
                error_code=error.get("code", "unknown"),
                error_message=error.get("message", "Init failed"),
            )

        data_block = init_resp.get("data", {})
        publish_id = data_block.get("publish_id", "")
        upload_url = data_block.get("upload_url", "")

        if not upload_url:
            return TikTokPostResult(
                success=False,
                error_code="no_upload_url",
                error_message="TikTok did not return an upload URL.",
            )

        # Step 2: Upload the video binary
        upload_headers = {
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
        }
        upload_resp = await self._request(
            "PUT", upload_url, data=video_bytes, headers=upload_headers, timeout=300
        )

        # Step 3: Poll for publish completion
        return await self._poll_publish_status(publish_id)

    async def _chunked_video_upload(
        self,
        video_bytes: bytes,
        caption: str,
        privacy_level: str,
        disable_duet: bool,
        disable_stitch: bool,
        disable_comment: bool,
        video_cover_timestamp_ms: int,
    ) -> TikTokPostResult:
        """Handle chunked upload for videos larger than CHUNK_SIZE_BYTES."""
        video_size = len(video_bytes)
        total_chunks = (video_size + CHUNK_SIZE_BYTES - 1) // CHUNK_SIZE_BYTES

        init_body = {
            "post_info": {
                "title": caption,
                "privacy_level": privacy_level,
                "disable_duet": disable_duet,
                "disable_stitch": disable_stitch,
                "disable_comment": disable_comment,
                "video_cover_timestamp_ms": video_cover_timestamp_ms,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": CHUNK_SIZE_BYTES,
                "total_chunk_count": total_chunks,
            },
        }

        init_resp = await self._request("POST", INIT_VIDEO_URL, json_body=init_body)

        error = init_resp.get("error", {})
        if error.get("code") and error["code"] != "ok":
            return TikTokPostResult(
                success=False,
                error_code=error.get("code", "unknown"),
                error_message=error.get("message", "Chunked init failed"),
            )

        data_block = init_resp.get("data", {})
        publish_id = data_block.get("publish_id", "")
        upload_url = data_block.get("upload_url", "")

        if not upload_url:
            return TikTokPostResult(
                success=False,
                error_code="no_upload_url",
                error_message="No upload URL returned for chunked upload.",
            )

        # Upload each chunk
        for chunk_idx in range(total_chunks):
            start = chunk_idx * CHUNK_SIZE_BYTES
            end = min(start + CHUNK_SIZE_BYTES, video_size)
            chunk_data = video_bytes[start:end]

            chunk_headers = {
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes {start}-{end - 1}/{video_size}",
            }

            await self._request(
                "PUT", upload_url, data=chunk_data, headers=chunk_headers, timeout=300
            )

        return await self._poll_publish_status(publish_id)

    # ------------------------------------------------------------------
    # Photo post
    # ------------------------------------------------------------------

    async def create_photo_post(
        self,
        image_data_b64: str,
        caption: str = "",
        hashtags: Optional[List[str]] = None,
        privacy_level: str = "PUBLIC_TO_EVERYONE",
        disable_comment: bool = False,
        auto_add_music: bool = True,
    ) -> TikTokPostResult:
        """
        Upload a photo post to TikTok (photo mode).

        Args:
            image_data_b64:  Base64-encoded image bytes (JPEG/PNG/WEBP).
            caption:         Post caption / description.
            hashtags:        List of hashtag strings (without #).
            privacy_level:   Privacy setting for the post.
            disable_comment: Disable comments on this post.
            auto_add_music:  Let TikTok auto-select background music.

        Returns:
            TikTokPostResult with publish_id and eventually post_id.

        Note:
            TikTok photo posts use the Content Posting API content/init endpoint
            and accept one or more images. This method posts a single image.
        """
        try:
            image_bytes = base64.b64decode(image_data_b64)
        except Exception as e:
            return TikTokPostResult(
                success=False,
                error_code="decode_error",
                error_message=f"Failed to decode base64 image data: {e}",
            )

        image_size = len(image_bytes)
        if image_size > MAX_PHOTO_SIZE_BYTES:
            return TikTokPostResult(
                success=False,
                error_code="file_too_large",
                error_message=f"Image size {image_size} bytes exceeds maximum {MAX_PHOTO_SIZE_BYTES}.",
            )

        full_caption = _build_caption(caption, hashtags)

        # Initialize photo post
        init_body = {
            "post_info": {
                "title": full_caption,
                "privacy_level": privacy_level,
                "disable_comment": disable_comment,
                "auto_add_music": auto_add_music,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "photo_cover_index": 0,
                "photo_images": [
                    {
                        "image_size": image_size,
                    }
                ],
            },
            "post_mode": "DIRECT_POST",
            "media_type": "PHOTO",
        }

        init_resp = await self._request("POST", INIT_PHOTO_URL, json_body=init_body)

        error = init_resp.get("error", {})
        if error.get("code") and error["code"] != "ok":
            return TikTokPostResult(
                success=False,
                error_code=error.get("code", "unknown"),
                error_message=error.get("message", "Photo init failed"),
            )

        data_block = init_resp.get("data", {})
        publish_id = data_block.get("publish_id", "")

        # Get the upload URL for the image
        upload_urls = data_block.get("upload_urls", [])
        if not upload_urls:
            # Some API versions use a single upload_url
            upload_url = data_block.get("upload_url", "")
            if not upload_url:
                return TikTokPostResult(
                    success=False,
                    error_code="no_upload_url",
                    error_message="No upload URL returned for photo post.",
                )
            upload_urls = [upload_url]

        # Upload the image
        upload_headers = {
            "Content-Type": "image/jpeg",
        }
        await self._request(
            "PUT", upload_urls[0], data=image_bytes, headers=upload_headers, timeout=120
        )

        return await self._poll_publish_status(publish_id)

    # ------------------------------------------------------------------
    # Post insights
    # ------------------------------------------------------------------

    async def get_post_insights(self, post_id: str) -> TikTokPostInsights:
        """
        Get engagement metrics for a specific TikTok post.

        Args:
            post_id: The TikTok video/post ID.

        Returns:
            TikTokPostInsights with view, like, comment, and share counts.
        """
        if not post_id:
            raise ValueError("post_id is required")

        query_body = {
            "filters": {
                "video_ids": [post_id],
            },
            "fields": [
                "id",
                "title",
                "create_time",
                "cover_image_url",
                "embed_link",
                "duration",
                "video_description",
                "like_count",
                "comment_count",
                "share_count",
                "view_count",
            ],
        }

        resp = await self._request("POST", VIDEO_QUERY_URL, json_body=query_body)

        error = resp.get("error", {})
        if error.get("code") and error["code"] != "ok":
            raise RuntimeError(
                f"TikTok API error: {error.get('code')} - {error.get('message')}"
            )

        videos = resp.get("data", {}).get("videos", [])
        if not videos:
            return TikTokPostInsights(post_id=post_id)

        video = videos[0]
        return TikTokPostInsights(
            post_id=video.get("id", post_id),
            title=video.get("title", ""),
            create_time=video.get("create_time", 0),
            view_count=video.get("view_count", 0),
            like_count=video.get("like_count", 0),
            comment_count=video.get("comment_count", 0),
            share_count=video.get("share_count", 0),
            duration=video.get("duration", 0),
            cover_image_url=video.get("cover_image_url", ""),
            embed_link=video.get("embed_link", ""),
            video_description=video.get("video_description", ""),
        )

    async def get_recent_posts(
        self, max_count: int = 20, cursor: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        List recent posts for the authenticated account.

        Args:
            max_count: Maximum number of posts to return (default 20, max 20).
            cursor:    Pagination cursor from a previous response.

        Returns:
            Dict with 'videos' list and optional 'cursor' / 'has_more'.
        """
        body: Dict[str, Any] = {
            "max_count": min(max_count, 20),
        }
        if cursor is not None:
            body["cursor"] = cursor

        fields = "id,title,create_time,cover_image_url,like_count,comment_count,share_count,view_count,duration"
        params = {"fields": fields}

        resp = await self._request("POST", VIDEO_LIST_URL, json_body=body, params=params)

        error = resp.get("error", {})
        if error.get("code") and error["code"] != "ok":
            raise RuntimeError(
                f"TikTok API error: {error.get('code')} - {error.get('message')}"
            )

        data = resp.get("data", {})
        return {
            "videos": data.get("videos", []),
            "cursor": data.get("cursor"),
            "has_more": data.get("has_more", False),
        }

    # ------------------------------------------------------------------
    # Account info
    # ------------------------------------------------------------------

    async def get_account_info(self) -> TikTokAccountInfo:
        """
        Get the authenticated TikTok account profile.

        Returns:
            TikTokAccountInfo with display name, follower counts, etc.
        """
        fields = (
            "open_id,union_id,display_name,avatar_url,avatar_url_100,"
            "bio_description,profile_deep_link,is_verified,"
            "follower_count,following_count,likes_count,video_count"
        )
        params = {"fields": fields}

        resp = await self._request("GET", USER_INFO_URL, params=params)

        error = resp.get("error", {})
        if error.get("code") and error["code"] != "ok":
            raise RuntimeError(
                f"TikTok API error: {error.get('code')} - {error.get('message')}"
            )

        user = resp.get("data", {}).get("user", {})
        return TikTokAccountInfo(
            open_id=user.get("open_id", ""),
            union_id=user.get("union_id", ""),
            display_name=user.get("display_name", ""),
            avatar_url=user.get("avatar_url", ""),
            avatar_url_100=user.get("avatar_url_100", ""),
            bio_description=user.get("bio_description", ""),
            profile_deep_link=user.get("profile_deep_link", ""),
            is_verified=user.get("is_verified", False),
            follower_count=user.get("follower_count", 0),
            following_count=user.get("following_count", 0),
            likes_count=user.get("likes_count", 0),
            video_count=user.get("video_count", 0),
        )

    # ------------------------------------------------------------------
    # Creator info (posting permissions)
    # ------------------------------------------------------------------

    async def get_creator_info(self) -> Dict[str, Any]:
        """
        Query the creator's posting permissions and limits.

        Returns information about:
        - Max video duration allowed
        - Whether comments/duet/stitch can be toggled
        - Available privacy levels
        """
        resp = await self._request("POST", CREATOR_INFO_URL, json_body={})

        error = resp.get("error", {})
        if error.get("code") and error["code"] != "ok":
            raise RuntimeError(
                f"TikTok API error: {error.get('code')} - {error.get('message')}"
            )

        return resp.get("data", {})

    # ------------------------------------------------------------------
    # Publish status polling
    # ------------------------------------------------------------------

    async def _poll_publish_status(self, publish_id: str) -> TikTokPostResult:
        """
        Poll the TikTok publish status endpoint until the post is
        published or fails.

        Polling interval: PUBLISH_POLL_INTERVAL_SEC
        Max attempts:     PUBLISH_POLL_MAX_ATTEMPTS
        """
        if not publish_id:
            return TikTokPostResult(
                success=False,
                error_code="no_publish_id",
                error_message="No publish_id to poll.",
            )

        for attempt in range(PUBLISH_POLL_MAX_ATTEMPTS):
            await asyncio.sleep(PUBLISH_POLL_INTERVAL_SEC)

            status_body = {"publish_id": publish_id}
            resp = await self._request("POST", PUBLISH_STATUS_URL, json_body=status_body)

            error = resp.get("error", {})
            if error.get("code") and error["code"] != "ok":
                # Some transient errors are normal during processing
                if attempt < PUBLISH_POLL_MAX_ATTEMPTS - 1:
                    continue
                return TikTokPostResult(
                    success=False,
                    publish_id=publish_id,
                    error_code=error.get("code", "unknown"),
                    error_message=error.get("message", "Status check failed"),
                )

            data = resp.get("data", {})
            status = data.get("status", "PROCESSING")

            if status == "PUBLISH_COMPLETE":
                return TikTokPostResult(
                    success=True,
                    publish_id=publish_id,
                    post_id=data.get("publicaly_available_post_id", ""),
                    status="PUBLISH_COMPLETE",
                    created_at=_now_iso(),
                )

            if status in ("FAILED", "PUBLISH_FAILED"):
                fail_reason = data.get("fail_reason", "Unknown failure")
                return TikTokPostResult(
                    success=False,
                    publish_id=publish_id,
                    status=status,
                    error_code="publish_failed",
                    error_message=fail_reason,
                )

            # Still processing -- keep polling
            if status in ("PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD", "SENDING_TO_USER_INBOX"):
                continue

        # Timed out
        return TikTokPostResult(
            success=False,
            publish_id=publish_id,
            status="TIMEOUT",
            error_code="poll_timeout",
            error_message=f"Publish status polling timed out after {PUBLISH_POLL_MAX_ATTEMPTS * PUBLISH_POLL_INTERVAL_SEC}s.",
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def to_dict(self, obj) -> dict:
        """Convert a dataclass result to a plain dict."""
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        return dict(obj)

    async def health_check(self) -> Dict[str, Any]:
        """
        Quick health check: verify the token is valid by fetching account info.

        Returns:
            Dict with 'healthy' bool, 'display_name', and 'error' if any.
        """
        try:
            info = await self.get_account_info()
            return {
                "healthy": True,
                "display_name": info.display_name,
                "follower_count": info.follower_count,
                "video_count": info.video_count,
                "checked_at": _now_iso(),
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "checked_at": _now_iso(),
            }
