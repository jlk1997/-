"""Wave 17: no fake closed loops. Paid stems, C2PA badges, vpay goods, invoice state."""

from pathlib import Path

from app.services.billing import wechat_vpay_product_id, wechat_vpay_ready
from app.services.c2pa import anchor_to_blockchain, c2pa_state
from app.services.stem_assets import isolation_is_sellable

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "app"
CLIENT = ROOT / "apps" / "client" / "src"
ZH = ROOT / "packages" / "i18n" / "src" / "locales" / "zh.ts"
EN = ROOT / "packages" / "i18n" / "src" / "locales" / "en.ts"


def test_full_mix_proxy_is_never_sellable():
    assert isolation_is_sellable("demucs")
    assert isolation_is_sellable("ffmpeg_bands")
    assert not isolation_is_sellable("full_mix_proxy")
    assert not isolation_is_sellable("unavailable")
    assert not isolation_is_sellable(None)


def test_paid_stem_export_rejects_proxy_zip():
    eco = (BACKEND / "services" / "ecosystem.py").read_text(encoding="utf-8")
    stems = eco.split("def _stem_pack_or_raise")[1].split("def _wav_or_raise")[0]
    assert "isolation_is_sellable(manifest.get(\"isolation\"))" in stems
    # The charge must still happen after the pack is built, so a rejected pack costs nothing.
    assert "if cost > 0 and not deduct_credits" in eco.split("stem_pack, extra_meta = _stem_pack_or_raise")[1][:400]
    work = (CLIENT / "packageStack" / "pages" / "work" / "index.tsx").read_text(encoding="utf-8")
    assert 'isolation === "full_mix_proxy"' in work


def test_export_quota_rows_follow_render_capability():
    eco = (BACKEND / "services" / "ecosystem.py").read_text(encoding="utf-8")
    caps = eco.split("def export_capabilities")[1].split("def get_member_export_quotas")[0]
    assert "ffmpeg_available()" in caps
    assert '"stems": ffmpeg' in caps
    assert '"ai_cover": not settings.use_mock_ai' in caps
    quotas = (CLIENT / "components" / "commercial" / "MemberExportQuotas.tsx").read_text(encoding="utf-8")
    assert "q.available !== false" in quotas
    assert "eco.exportQuotaUnavailable" in quotas
    assert "exportQuotaUnavailable:" in ZH.read_text(encoding="utf-8")
    assert "exportQuotaUnavailable:" in EN.read_text(encoding="utf-8")


def test_c2pa_state_separates_sidecar_from_embedded():
    assert c2pa_state(None) == "none"
    assert c2pa_state({}) == "none"
    assert c2pa_state({"c2pa_done": True}) == "sidecar"
    assert c2pa_state({"c2pa_done": True, "c2pa_embedded": False}) == "sidecar"
    assert c2pa_state({"c2pa_done": True, "c2pa_embedded": True}) == "embedded"


def test_c2pa_badges_never_claim_verified_for_sidecar():
    works = (BACKEND / "api" / "routes" / "works.py").read_text(encoding="utf-8")
    assert 'c2pa_verified=state == "embedded"' in works
    assert "c2pa_state=state" in works
    for module in ("services/distribution/passport.py", "services/royalty/sync_desk.py"):
        src = (BACKEND / module).read_text(encoding="utf-8")
        assert 'c2pa_state(pps) == "embedded"' in src
        assert 'bool(pps.get("c2pa_done") or pps.get("c2pa"))' not in src
    badges = (CLIENT / "components" / "ui" / "PostProcessBadges.tsx").read_text(encoding="utf-8")
    assert "w.c2paEmbedded" in badges
    assert "w.c2paSidecar" in badges
    zh = ZH.read_text(encoding="utf-8")
    assert 'c2paSidecar: "C2PA 只有随附文件"' in zh
    assert "C2PA 已锚定" not in zh


def test_anchor_without_rpc_does_not_invent_a_tx():
    from app.config import settings

    original_enabled = settings.blockchain_anchor_enabled
    original_rpc = settings.blockchain_rpc_url
    try:
        settings.blockchain_anchor_enabled = True
        settings.blockchain_rpc_url = ""
        record = anchor_to_blockchain("deadbeef", "work-1")
        assert record is not None
        assert record["status"] == "not_anchored"
        assert record["tx_hash"] is None
    finally:
        settings.blockchain_anchor_enabled = original_enabled
        settings.blockchain_rpc_url = original_rpc

    c2pa = (BACKEND / "services" / "c2pa.py").read_text(encoding="utf-8")
    assert "mock_anchored" not in c2pa


def test_unmapped_vpay_goods_blocks_the_order():
    # Shipping with an empty goods map must not fall back to our own product id.
    assert wechat_vpay_product_id("pack_10") == ""
    assert wechat_vpay_product_id("nope") == ""
    assert wechat_vpay_ready("pack_10") is False
    vpay = (BACKEND / "services" / "virtual_payment.py").read_text(encoding="utf-8")
    guard = vpay.split("async def create_vpay_order")[1]
    assert "settings.wechat_vpay_enabled and not wechat_vpay_product_id(pack_id)" in guard
    assert "status_code=503" in guard.split("wechat_vpay_product_id(pack_id)")[1][:300]
    billing = (BACKEND / "services" / "billing.py").read_text(encoding="utf-8")
    assert "or product_id" not in billing.split("def wechat_vpay_product_id")[1].split("def ")[1]


def test_pricing_marks_unconfigured_vpay():
    billing = (BACKEND / "services" / "billing.py").read_text(encoding="utf-8")
    assert '"wechat_vpay_enabled": wechat_vpay_ready(pid)' in billing
    pricing = (CLIENT / "packageStack" / "pages" / "pricing" / "index.tsx").read_text(encoding="utf-8")
    assert "pack.wechat_vpay_enabled === false" in pricing
    assert "p.vpayNotConfigured" in pricing
    paywall = (CLIENT / "components" / "ui" / "CreditsPaywallSheet.tsx").read_text(encoding="utf-8")
    assert "pr.vpayNotConfigured" in paywall
    assert 'vpayNotConfigured: "小程序虚拟支付未配置，请在电脑浏览器购买"' in ZH.read_text(encoding="utf-8")
    assert "vpayNotConfigured:" in EN.read_text(encoding="utf-8")


def test_invoice_order_is_not_paid_until_ops_confirms():
    sync = (BACKEND / "services" / "royalty" / "sync_desk.py").read_text(encoding="utf-8")
    assert 'status="pending_invoice" if pay_method == "invoice" else "paid"' in sync
    assert 'paid_at=datetime.utcnow() if pay_method == "credits" else None' in sync
    desk = (CLIENT / "packageCommerce" / "pages" / "sync-desk" / "index.tsx").read_text(encoding="utf-8")
    assert "statusLabel(order.status || \"\", copy.creatorUi.status)" in desk
    assert 'order.status === "pending_invoice"' in desk
    assert "s.invoiceWaitOps" in desk
    zh = ZH.read_text(encoding="utf-8")
    assert 'pending_invoice: "待对公入账"' in zh
    assert "invoiceWaitOps:" in zh


def test_user_and_ops_share_one_money_vocabulary():
    admin = (CLIENT / "packageOps" / "pages" / "admin" / "index.tsx").read_text(encoding="utf-8")
    assert 'statusLabel(order.status || "pending_invoice", copy.creatorUi.status)' in admin
    assert 'statusLabel(b.status || "", copy.creatorUi.status)' in admin
    for key in ("pending_invoice:", "approved:", "voided:", "paid:"):
        assert key in ZH.read_text(encoding="utf-8")
        assert key in EN.read_text(encoding="utf-8")


def test_friday_queue_aggregates_manual_steps_only():
    ops = (BACKEND / "services" / "ops_dashboard.py").read_text(encoding="utf-8")
    assert '"settlement_drafts": int(settlement_drafts)' in ops
    assert '"pending_invoices": int(pending_invoices)' in ops
    friday = ops.split("friday_queue = {")[1].split("}")[0]
    for key in ("settlement_drafts", "pending_invoices", "pending_kyc", "pending_payouts"):
        assert key in friday
    assert '"auto_payout": False' in friday
    admin = (CLIENT / "packageOps" / "pages" / "admin" / "index.tsx").read_text(encoding="utf-8")
    assert "a.fridayQueueTitle" in admin
    assert "a.fridaySettlementDrafts" in admin
    assert "a.fridayPayoutReceipts" in admin
    assert "系统不会自动打款" in ZH.read_text(encoding="utf-8")
    assert "Nothing pays out automatically." in EN.read_text(encoding="utf-8")


def test_auto_payout_stays_manual_only():
    wallet = (BACKEND / "services" / "royalty" / "wallet.py").read_text(encoding="utf-8")
    auto = wallet.split("def try_auto_payout")[1].split("def run_auto_payouts")[0]
    assert "return None" in auto
    assert "paid_manual" not in auto.split('"""')[2]
