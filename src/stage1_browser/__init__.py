"""
Stage 1: Browser Automation, Stealth Contexts, and Account Rotation
"""
from .account_vault import AccountVault, SocialAccount
from .stealth_context import create_stealth_context, human_scroll
from .checkpoint import CheckpointManager

__all__ = [
    "AccountVault",
    "SocialAccount",
    "create_stealth_context",
    "human_scroll",
    "CheckpointManager"
]
