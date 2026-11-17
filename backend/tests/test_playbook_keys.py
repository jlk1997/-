from app.services.harvest.playbooks import CHANNEL_STEPS, PLAYBOOKS


def test_playbook_keys_do_not_split_tiktok_or_duplicate_wechat():
    assert "tiktok" not in CHANNEL_STEPS
    assert "tiktok_music" in CHANNEL_STEPS
    assert list(CHANNEL_STEPS.keys()).count("wechat_channels") == 1
    assert "扫码" in CHANNEL_STEPS["wechat_channels"]["login_hints"]
    assert PLAYBOOKS["amazon_music"]["portal"].startswith("https://artists.amazon.com")
    assert CHANNEL_STEPS["amazon_music"]["stats_url"].startswith("https://artists.amazon.com")
    assert any("amazonmusic.com" in url for url in CHANNEL_STEPS["amazon_music"]["stats_urls"])
