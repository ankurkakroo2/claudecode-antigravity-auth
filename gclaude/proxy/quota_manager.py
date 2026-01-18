"""Quota Manager for Antigravity Integration.

Antigravity-only quota routing.
"""

import json
import logging
import asyncio
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from gclaude.proxy.antigravity_auth import (
    AntigravityAuthManager,
    discover_project_id,
    get_valid_access_token,
)
from gclaude.proxy.antigravity_client import (
    AntigravityAuthError,
    AntigravityClient,
    AntigravityClientError,
    AntigravityRateLimitError,
    convert_gemini_to_anthropic_format,
)

logger = logging.getLogger(__name__)


class QuotaType(Enum):
    """Type of quota source."""

    ANTIGRAVITY = "antigravity"  # OAuth-based Antigravity endpoints


class QuotaState:
    """Tracks quota state."""

    def __init__(self, quota_type: QuotaType):
        self.quota_type = quota_type
        self.rate_limited_until: Optional[datetime] = None
        self.consecutive_failures = 0
        self.last_success: Optional[datetime] = None
        self.total_requests = 0
        self.total_failures = 0

    def is_available(self) -> bool:
        if self.rate_limited_until:
            if datetime.now() < self.rate_limited_until:
                return False
            self.rate_limited_until = None
        return True

    def mark_success(self):
        self.last_success = datetime.now()
        self.consecutive_failures = 0
        self.total_requests += 1

    def mark_failure(self, is_rate_limit: bool = False, backoff_seconds: int = 60):
        self.total_failures += 1
        self.consecutive_failures += 1

        if is_rate_limit:
            self.rate_limited_until = datetime.now() + timedelta(seconds=backoff_seconds)
            logger.warning(
                "Rate limited - backing off %s seconds until %s",
                backoff_seconds,
                self.rate_limited_until,
            )


class QuotaManager:
    """Manages Antigravity quota + OAuth usage."""

    def __init__(self, auth_manager: AntigravityAuthManager, use_antigravity: bool = True):
        self.auth_manager = auth_manager
        self.use_antigravity = use_antigravity

        self.antigravity_state = QuotaState(QuotaType.ANTIGRAVITY)

        # Rate limit backoff settings
        # Prefer server-provided retryDelay (usually a few seconds);
        # this is just a cap for worst cases.
        self.rate_limit_backoff_seconds = 300
        self.max_consecutive_failures = 5

    def get_preferred_quota_type(self) -> QuotaType:
        return QuotaType.ANTIGRAVITY

    async def generate_content(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        stream: bool = False,
        **kwargs,
    ) -> Any:
        import sys

        logger.debug(f"generate_content: model={model}, stream={stream}")
        logger.debug(f"generate_content kwargs: {list(kwargs.keys())}")

        if not self.use_antigravity:
            raise Exception("Antigravity is disabled")

        rate_limited_until = self.antigravity_state.rate_limited_until
        if rate_limited_until and datetime.now() < rate_limited_until:
            retry_after = (rate_limited_until - datetime.now()).total_seconds()
            wait_seconds = max(retry_after, 0)
            logger.warning("Antigravity rate limited; waiting %ss", round(wait_seconds, 2))
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
        # Clear expired backoff if needed.
        self.antigravity_state.is_available()

        result = await self._try_antigravity(model, messages, stream, **kwargs)
        if result is not None:
            return result

        logger.error("Antigravity API unavailable")
        sys.stdout.flush()
        raise Exception(
            "Antigravity API unavailable. Please check your Antigravity quota or OAuth access."
        )

    async def _try_antigravity(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        stream: bool = False,
        **kwargs,
    ) -> Optional[Any]:
        logger.debug(f"_try_antigravity: model={model}")

        access_token = await get_valid_access_token(self.auth_manager)
        logger.debug(f"_try_antigravity: access_token={bool(access_token)}")
        if not access_token:
            logger.warning("No valid Antigravity access token available")
            return None

        account = self.auth_manager.get_available_account()
        logger.debug(f"_try_antigravity: account={bool(account)}")
        if not account:
            logger.warning("No valid Antigravity account available")
            return None

        if not getattr(account, "_project_id_checked", False):
            try:
                discovered_project_id = await discover_project_id(
                    access_token, project_id_hint=account.project_id
                )
                if discovered_project_id and discovered_project_id != account.project_id:
                    logger.info("Updating Antigravity project id from loadCodeAssist")
                    account.project_id = discovered_project_id
                    self.auth_manager.add_account(account)
            except Exception as e:
                logger.warning(f"Project ID discovery failed: {e}")
            account._project_id_checked = True

        project_id = account.project_id
        logger.debug(f"_try_antigravity: project_id={project_id}")

        client = AntigravityClient(access_token, project_id)

        try:
            logger.debug(f"_try_antigravity: calling client, stream={stream}")
            if stream:
                upstream_stream = client.stream_generate_content(model, messages, **kwargs)

                async def wrapped_stream():
                    first_chunk = True
                    try:
                        async for chunk in upstream_stream:
                            if first_chunk:
                                self.antigravity_state.mark_success()
                                first_chunk = False
                            yield chunk

                        if first_chunk:
                            # Stream ended without yielding; avoid permanent lockout.
                            self.antigravity_state.mark_success()

                    except AntigravityRateLimitError as e:
                        logger.warning(f"Antigravity rate limited (stream): {e}")
                        retry_after = getattr(e, "retry_after_seconds", None)
                        if not isinstance(retry_after, (int, float)) or retry_after <= 0:
                            retry_after = 5
                        backoff = min(int(retry_after) + 1, self.rate_limit_backoff_seconds)
                        self.antigravity_state.mark_failure(
                            is_rate_limit=True, backoff_seconds=backoff
                        )
                        raise

                    except AntigravityAuthError as e:
                        logger.error(f"Antigravity auth error (stream): {e}")
                        self.antigravity_state.mark_failure(is_rate_limit=False)
                        raise

                    except AntigravityClientError as e:
                        logger.warning(f"Antigravity client error (stream): {e}")
                        self.antigravity_state.mark_failure(is_rate_limit=False)
                        raise

                    except Exception as e:
                        logger.error(f"Unexpected Antigravity error (stream): {e}")
                        self.antigravity_state.mark_failure(is_rate_limit=False)
                        raise

                return wrapped_stream()

            response = await client.generate_content(model, messages, **kwargs)
            self.antigravity_state.mark_success()
            return convert_gemini_to_anthropic_format(
                response, kwargs.get("tool_schemas")
            )

        except AntigravityRateLimitError as e:
            logger.warning(f"Antigravity rate limited: {e}")
            retry_after = getattr(e, "retry_after_seconds", None)
            if not isinstance(retry_after, (int, float)) or retry_after <= 0:
                retry_after = 5
            backoff = min(int(retry_after) + 1, self.rate_limit_backoff_seconds)
            self.antigravity_state.mark_failure(is_rate_limit=True, backoff_seconds=backoff)
            raise

        except AntigravityAuthError as e:
            logger.error(f"Antigravity auth error: {e}")
            self.antigravity_state.mark_failure(is_rate_limit=False)
            raise

        except AntigravityClientError as e:
            logger.warning(f"Antigravity client error: {e}")
            self.antigravity_state.mark_failure(is_rate_limit=False)
            raise

        except Exception as e:
            logger.error(f"Unexpected Antigravity error: {e}")
            self.antigravity_state.mark_failure(is_rate_limit=False)
            return None

    def get_status(self) -> Dict[str, Any]:
        return {
            "antigravity": {
                "enabled": self.use_antigravity,
                "available": self.antigravity_state.is_available(),
                "accounts": self.auth_manager.account_count(),
                "consecutive_failures": self.antigravity_state.consecutive_failures,
                "rate_limited_until": self.antigravity_state.rate_limited_until.isoformat()
                if self.antigravity_state.rate_limited_until
                else None,
            },
            "preferred": self.get_preferred_quota_type().value,
        }

    def reset_antigravity_failures(self):
        self.antigravity_state.consecutive_failures = 0
        self.antigravity_state.rate_limited_until = None
        logger.info("Reset Antigravity failure state")
