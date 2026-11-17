"""Copilot tool routing tests."""

from app.copilot.service import _pick_tool, _tool_explain_derivative, _tool_suggest_mode, execute_tool


def test_pick_tool_derivative():
    name, args = _pick_tool("什么是 remix 和翻唱的区别")
    assert name == "explain_derivative"
    assert args["topic"] in ("remix", "cover")


def test_pick_tool_journey():
    name, args = _pick_tool("帮我规划一条情绪旅程")
    assert name == "plan_journey_hint"
    assert "text_intent" in args


def test_pick_tool_stems_vs_master_goes_to_release():
    name, args = _pick_tool("上架要传分轨还是母带？")
    assert name == "open_creator_os"
    assert args["target"] == "release"
    result = execute_tool("open_creator_os", {"target": "release"})
    assert "立体声母带" in result["explanation"]
    assert "原创证明" in result["explanation"]


def test_pick_tool_creator_os():
    name, args = _pick_tool("怎么去发行并对账")
    assert name == "open_creator_os"
    assert args["target"] in {"hub", "release", "accounts", "settlements"}
    result = execute_tool("open_creator_os", {"target": "release"})
    assert result["navigate"] == "release"
    assert "连接器" in result["explanation"]
    assert "签约" not in result["explanation"]


def test_pick_tool_creator_os_wallet_and_sync():
    name, args = _pick_tool("去看法币钱包和提现")
    assert name == "open_creator_os"
    assert args["target"] == "wallet"
    result = execute_tool("open_creator_os", {"target": "syncDesk"})
    assert result["navigate"] == "syncDesk"
    assert "同步" in result["explanation"] or "sync" in result["explanation"].lower()
    wallet = execute_tool("open_creator_os", {"target": "wallet"})
    assert "打款" in wallet["explanation"]
    assert "不能加总" in wallet["explanation"]
    assert "VS-W" in wallet["explanation"]
    deliveries = execute_tool("open_creator_os", {"target": "deliveries"})
    assert "加急" in deliveries["explanation"]
    assert "等登录一键" in deliveries["explanation"]
    assert "签约" not in deliveries["explanation"]
    receipt, receipt_args = _pick_tool("提现回单在哪看")
    assert receipt == "open_creator_os"
    assert receipt_args["target"] == "wallet"


def test_pick_tool_emotion_calendar():
    name, args = _pick_tool("去看情绪日历再开试听局")
    assert name == "open_creator_os"
    assert args["target"] == "emotionCalendar"
    result = execute_tool("open_creator_os", {"target": "emotionCalendar"})
    assert result["navigate"] == "emotionCalendar"


def test_pick_tool_harvest_goes_to_accounts_not_csv():
    name, args = _pick_tool("店里的钱对不上，怎么收割")
    assert name == "open_creator_os"
    assert args["target"] == "accounts"
    result = execute_tool("open_creator_os", {"target": "accounts"})
    assert result["navigate"] == "accounts"
    assert "连" in result["explanation"]
    csv_name, csv_args = _pick_tool("帮我导入官方 CSV")
    assert csv_name == "open_creator_os"
    assert csv_args["target"] == "dataImport"


def test_pick_tool_beautify_beats_bare_workbench():
    name, _ = _pick_tool("去工作台")
    assert name == "open_beautify"
    label, args = _pick_tool("打开发行工作台")
    assert label == "open_creator_os"
    assert args["target"] in {"hub", "release"}
    pack, _ = _pick_tool("套一个效果包美化一下")
    assert pack == "open_beautify"
    master, _ = _pick_tool("去美化母带")
    assert master == "open_beautify"
    style, _ = _pick_tool("用 lo-fi 风格包")
    assert style == "apply_preset"
    result = execute_tool("open_beautify", {})
    assert "workbench-lite" in result["navigate"]
    assert "风格包" in result["explanation"]
    assert result["tool"] == "open_beautify"


def test_execute_suggest_mode():
    result = execute_tool("suggest_mode", {"user_text": "我想写一首带歌词的歌"})
    assert result["mode"] == "vocals"


def test_explain_derivative():
    result = _tool_explain_derivative("anchor")
    assert "锚定" in result["explanation"] or "延续" in result["explanation"]
