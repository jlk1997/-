# Distribution & split agreement

**Effective date: 2026-09-02**  
**Version: 2026-09-02**

This agreement is between you and the BitYin operator. It covers issuing AI-generated works to streaming stores through platform seats or a musician account you authorized.

## 1. Two modes

1. **Self-release**: you keep the copyright. You upload from your own musician or distributor account. After you authorize a seat, we harvest that dashboard, take a 10% service fee, and credit the net to your fiat wallet. Without a seat, money never hits the platform.
2. **Label split**: you authorize platform seats to deliver and harvest store dashboards. Default cut is 20%; the first three live label works are promotional 10%. A signed 10% / 20% / 30% tier wins. The rest goes to your fiat wallet.

Partner DistroKid / TuneCore APIs stay stubs. They are not the settlement source.

## 2. Data and settlement

The label money path is authorized seat harvest (platform or your seat). Matched rows can settle the same day or next day — no T+45 official statement wait.

Official CSV / partner APIs are an ops side path and cannot overwrite a harvest already booked for the same work / channel / period. Unmatched harvest rows stay in the ops unassigned queue and never enter a wallet. Account-total rows split by play share of matched tracks; leftovers stay unmatched.

The same harvest credit is split on the sheet. Max 4 people, must total 100%. Later harvest increases settle the delta only; decreases claw back each share at the locked cut.

Credit tips and royalty fiat never add together. Radio warmup is in-house, not store royalties.

## 3. Withdrawals

Available balance must meet the minimum. China: WeChat, Alipay, bank card. Overseas: PayPal / Stripe. Withdrawals require your own payout account and a verified identity. Paid is marked only after ops transfers money. The Friday job never auto-pays.

## 4. AI disclosure

Released works must keep the AI-generated disclosure. Do not remove labels required by the platform or the store.

## 5. Creator connector

The connector is your key, not our crawler. It only reads visible data on an official musician dashboard you already logged into, and only in the range you checked and tapped Sync. We do not store store passwords, solve challenges, or promise that Spotify (or any store without an official API) will stay automatable.

Default sync covers plays, tracks, and regions, plus an estimated revenue range for your desk. Estimates are not settlement and cannot be withdrawn; actual amounts follow each store's official statement. Using synced rows for settlement (10% self-release fee) needs a second explicit grant and this agreement. You can revoke settle/upload scopes without disconnecting the store.

DOM reads happen only when you tap Sync. Official CSV exports and future official APIs come first.
