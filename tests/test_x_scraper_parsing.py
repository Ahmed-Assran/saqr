import pytest
from src.stage1_browser.account_vault import AccountVault
from src.stage1_browser.checkpoint import CheckpointManager
from src.stage2_scrapers.x_scraper import XScraper

def test_parse_modern_x_graphql_user_and_tweet(tmp_path):
    vault_file = tmp_path / "accounts.json"
    vault_file.write_text("{}", encoding="utf-8")
    vault = AccountVault(vault_file)
    cp = CheckpointManager(tmp_path)
    scraper = XScraper(vault, cp, tmp_path, {}, {})

    # Modern 2025/2026 Twitter schema
    user_res = {
        "result": {
            "__typename": "User",
            "rest_id": "999888777",
            "core": {
                "name": "سعودي يتداول",
                "screen_name": "saudi_trader_99"
            },
            "profile_bio": {
                "description": "مهتم بالأسهم الأمريكية وعقود الأوبشن في الرياض"
            },
            "location": {
                "location": "الرياض، المملكة العربية السعودية"
            },
            "relationship_counts": {
                "followers": 1420,
                "following": 310
            },
            "is_blue_verified": True
        }
    }

    tweet_data = {
        "rest_id": "1122334455",
        "legacy": {
            "id_str": "1122334455",
            "full_text": "شباب أحد جرب تداول عقود الأوبشن على $TSLA و $NVDA عبر دراية جلوبل؟ هل التنفيذ سريع؟",
            "created_at": "Wed Oct 21 16:00:00 +0000 2026"
        }
    }

    lead = scraper.parse_user_and_tweet_data(user_res, tweet_data, "search_tweet", "test_query")
    assert lead is not None
    assert lead.platform == "x"
    assert lead.user_id == "999888777"
    assert lead.username == "saudi_trader_99"
    assert lead.display_name == "سعودي يتداول"
    assert "الأوبشن" in lead.bio
    assert lead.location == "الرياض، المملكة العربية السعودية"
    assert lead.followers_count == 1420
    assert lead.verified is True
    assert len(lead.triggers) == 1
    assert "$TSLA" in lead.triggers[0].cashtags
    assert "$NVDA" in lead.triggers[0].cashtags


def test_parse_legacy_x_graphql_user_and_tweet(tmp_path):
    vault_file = tmp_path / "accounts2.json"
    vault_file.write_text("{}", encoding="utf-8")
    vault = AccountVault(vault_file)
    cp = CheckpointManager(tmp_path)
    scraper = XScraper(vault, cp, tmp_path, {}, {})

    # Legacy Twitter schema
    user_res = {
        "result": {
            "__typename": "User",
            "rest_id": "123456",
            "legacy": {
                "screen_name": "legacy_user",
                "name": "Legacy Name",
                "description": "Legacy Bio",
                "location": "Jeddah",
                "followers_count": 500,
                "friends_count": 200,
                "verified": False
            }
        }
    }

    tweet_data = {
        "rest_id": "778899",
        "legacy": {
            "id_str": "778899",
            "full_text": "تداول الأسهم النقية في السوق الأمريكي",
            "created_at": "Wed Oct 21 12:00:00 +0000 2026"
        }
    }

    lead = scraper.parse_user_and_tweet_data(user_res, tweet_data, "search_tweet", "test_query")
    assert lead is not None
    assert lead.username == "legacy_user"
    assert lead.display_name == "Legacy Name"
    assert lead.followers_count == 500
