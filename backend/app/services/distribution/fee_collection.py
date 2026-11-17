"""How the 10% self-release share is collected.

The user's store pays the user, not us. We do not debit that account.
The signed license records the rate. Finance invoices it, or nets it
against money the platform label already holds for the same person.
"""

SELF_RELEASE_FEE_COLLECTION = "recorded_obligation"

COLLECTION_OPTIONS = (
    {
        "id": "recorded_obligation",
        "label": "记在分发许可上，财务按月收",
        "chosen": True,
        "moves_money": False,
    },
    {
        "id": "offset_label_income",
        "label": "从平台厂牌已经代收的收入里抵",
        "chosen": False,
        "moves_money": False,
    },
    {
        "id": "service_fee",
        "label": "改成固定服务费或额度，不再按店铺收入抽成",
        "chosen": False,
        "moves_money": False,
    },
)


def fee_collection_policy() -> dict:
    return {
        "self_release": SELF_RELEASE_FEE_COLLECTION,
        "label_rate_default": 20,
        "self_release_rate_default": 10,
        "debits_user_store": False,
        "options": list(COLLECTION_OPTIONS),
    }
