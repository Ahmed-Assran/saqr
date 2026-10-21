"""
Account Vault and Multi-Account Rotation State Machine
Manages browser sessions, persistent cookie state files, proxies, and cooldown windows.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SocialAccount:
    account_id: str
    platform: str  # "x" or "tiktok"
    username: str
    proxy_url: Optional[str] = None
    storage_state_path: str = ""
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    viewport: Dict[str, int] = field(default_factory=lambda: {"width": 1440, "height": 900})
    status: str = "active"  # "active", "cooldown", "challenged", "banned"
    requests_in_window: int = 0
    cooldown_until: Optional[str] = None

    def is_available(self) -> bool:
        """Check if account is active and not currently in cooldown."""
        if self.status != "active":
            return False
        if self.cooldown_until:
            try:
                cooldown_time = datetime.fromisoformat(self.cooldown_until)
                if datetime.now(timezone.utc) < cooldown_time:
                    return False
                # Cooldown expired, restore
                self.cooldown_until = None
                self.requests_in_window = 0
            except ValueError:
                self.cooldown_until = None
        return True

    def record_request(self, max_requests: int = 20, cooldown_minutes: int = 45) -> bool:
        """
        Record a request. Returns True if account is still active,
        or False if it has hit the limit and entered cooldown.
        """
        self.requests_in_window += 1
        if self.requests_in_window >= max_requests:
            self.trigger_cooldown(minutes=cooldown_minutes, reason="Window request ceiling reached")
            return False
        return True

    def trigger_cooldown(self, minutes: int = 45, reason: str = "") -> None:
        """Put account on cooldown for specified minutes."""
        cooldown_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        self.cooldown_until = cooldown_time.isoformat()
        logger.info(
            f"Account [{self.account_id}] entered cooldown for {minutes}m. "
            f"Reason: {reason or 'Scheduled rotation'}. Resumes at {self.cooldown_until}"
        )

    def trigger_circuit_breaker(self, status_code: int = 429) -> None:
        """Circuit breaker triggered on 429, 403, or bot challenge."""
        if status_code == 429:
            self.trigger_cooldown(minutes=60, reason="HTTP 429 Rate Limit Encountered")
        elif status_code == 403:
            self.status = "challenged"
            logger.warning(f"Account [{self.account_id}] marked as CHALLENGED (HTTP 403)")
        else:
            self.trigger_cooldown(minutes=60, reason=f"HTTP {status_code} Circuit Breaker")


class AccountVault:
    def __init__(self, config_path: Path | str, base_dir: Optional[Path] = None):
        self.config_path = Path(config_path)
        self.base_dir = base_dir or self.config_path.parent.parent
        self.rotation_policy: Dict[str, Any] = {
            "x_max_requests_per_window": 20,
            "tiktok_max_videos_per_window": 20,
            "cooldown_minutes": 45,
            "circuit_breaker_cooldown_minutes": 60,
            "jitter_seconds_min": 3.5,
            "jitter_seconds_max": 8.2,
        }
        self.accounts: List[SocialAccount] = []
        self._load_accounts()

    def _load_accounts(self) -> None:
        """Load accounts from JSON file."""
        if not self.config_path.exists():
            # Check example file
            example_path = self.config_path.with_name("accounts_pool.example.json")
            if example_path.exists():
                self.config_path = example_path
            else:
                logger.warning(f"Accounts pool config not found at {self.config_path}")
                return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "rotation_policy" in data:
                self.rotation_policy.update(data["rotation_policy"])

            self.accounts = []
            for item in data.get("accounts", []):
                acc = SocialAccount(
                    account_id=item["account_id"],
                    platform=item["platform"].lower(),
                    username=item["username"],
                    proxy_url=item.get("proxy_url"),
                    storage_state_path=item.get("storage_state_path", ""),
                    user_agent=item.get("user_agent", SocialAccount.user_agent),
                    viewport=item.get("viewport", {"width": 1440, "height": 900}),
                    status=item.get("status", "active"),
                    requests_in_window=item.get("requests_in_window", 0),
                    cooldown_until=item.get("cooldown_until"),
                )
                self.accounts.append(acc)
            logger.info(f"Loaded {len(self.accounts)} accounts from {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to load accounts pool from {self.config_path}: {e}")

    def save_accounts(self) -> None:
        """Persist account states back to config."""
        try:
            payload = {
                "rotation_policy": self.rotation_policy,
                "accounts": [asdict(a) for a in self.accounts],
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save account pool to {self.config_path}: {e}")

    def get_available_account(self, platform: str) -> Optional[SocialAccount]:
        """Find next available active account for the specified platform."""
        platform = platform.lower()
        for account in self.accounts:
            if account.platform == platform and account.is_available():
                return account
        return None

    def get_account_by_id(self, account_id: str) -> Optional[SocialAccount]:
        """Lookup account by unique ID."""
        for account in self.accounts:
            if account.account_id == account_id:
                return account
        return None

    def rotate_or_cooldown(self, account: SocialAccount) -> Optional[SocialAccount]:
        """
        Record a request, trigger cooldown if needed, and return the next active account.
        """
        max_requests = (
            self.rotation_policy.get("x_max_requests_per_window", 20)
            if account.platform == "x"
            else self.rotation_policy.get("tiktok_max_videos_per_window", 20)
        )
        cooldown_mins = self.rotation_policy.get("cooldown_minutes", 45)

        still_active = account.record_request(max_requests=max_requests, cooldown_minutes=cooldown_mins)
        self.save_accounts()

        if still_active:
            return account
        return self.get_available_account(account.platform)

    def resolve_storage_state(self, account: SocialAccount) -> Optional[str]:
        """Resolve storage state JSON file path on disk."""
        if not account.storage_state_path:
            return None
        path = Path(account.storage_state_path)
        if not path.is_absolute():
            path = self.base_dir / path
        if path.exists() and path.stat().st_size > 0:
            return str(path)
        return None
