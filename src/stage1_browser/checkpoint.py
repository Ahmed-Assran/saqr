"""
Atomic Checkpoint Manager
Safely persists scraping progress to JSON files to enable --resume after interruptions.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class CheckpointManager:
    def __init__(self, checkpoints_dir: Path | str, run_date: Optional[str] = None):
        self.checkpoints_dir = Path(checkpoints_dir)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.run_date = run_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.checkpoint_file = self.checkpoints_dir / f"checkpoint_{self.run_date}.json"

        self.state: Dict[str, Any] = {
            "run_date": self.run_date,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed_x_queries": [],
            "completed_x_brokers": [],
            "completed_tiktok_queries": [],
            "completed_tiktok_videos": [],
            "total_raw_leads_staged": 0,
            "processed_user_ids": [],
            "stage_status": {
                "stage1": "not_started",
                "stage2": "not_started",
                "stage3": "not_started",
            },
        }
        self.load()

    def load(self) -> None:
        """Load existing checkpoint if present."""
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.state.update(data)
                logger.info(
                    f"Loaded checkpoint from {self.checkpoint_file} "
                    f"({len(self.state.get('completed_x_queries', []))} X queries completed)"
                )
            except Exception as e:
                logger.warning(f"Could not read checkpoint file {self.checkpoint_file}: {e}")

    def save(self) -> None:
        """Atomically persist state using temporary file rename."""
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        temp_file = self.checkpoint_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.checkpoint_file)
            logger.debug(f"Atomically saved checkpoint to {self.checkpoint_file}")
        except Exception as e:
            logger.error(f"Failed saving checkpoint to {self.checkpoint_file}: {e}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

    def is_x_query_completed(self, query: str) -> bool:
        return query in self.state.get("completed_x_queries", [])

    def mark_x_query_completed(self, query: str) -> None:
        if query not in self.state["completed_x_queries"]:
            self.state["completed_x_queries"].append(query)
            self.save()

    def is_x_broker_completed(self, broker_handle: str) -> bool:
        return broker_handle in self.state.get("completed_x_brokers", [])

    def mark_x_broker_completed(self, broker_handle: str) -> None:
        if broker_handle not in self.state["completed_x_brokers"]:
            self.state["completed_x_brokers"].append(broker_handle)
            self.save()

    def is_tiktok_query_completed(self, query: str) -> bool:
        return query in self.state.get("completed_tiktok_queries", [])

    def mark_tiktok_query_completed(self, query: str) -> None:
        if query not in self.state["completed_tiktok_queries"]:
            self.state["completed_tiktok_queries"].append(query)
            self.save()

    def is_user_processed(self, user_id: str) -> bool:
        return user_id in self.state.get("processed_user_ids", [])

    def add_processed_user(self, user_id: str) -> None:
        if user_id not in self.state["processed_user_ids"]:
            self.state["processed_user_ids"].append(user_id)

    def set_stage_status(self, stage: str, status: str) -> None:
        if "stage_status" not in self.state:
            self.state["stage_status"] = {}
        self.state["stage_status"][stage] = status
        self.save()
