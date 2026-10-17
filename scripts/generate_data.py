"""Generate synthetic raw data for a fictional client, Northwind Outdoor Co..

Every number is invented. The output mimics what lands in BigQuery in a real
setup: one raw table per ad platform (as Airbyte loads them) and a GA4 export
with one events_YYYYMMDD table per day.

Built-in problems, so the Dataform models have real work to do:
  * Ad data starts in October 2025, but the GA4 export was only linked on
    2 Feb 2026 and can't backfill.
  * Google Ads reports cost in micros; Meta sends spend as a string and
    re-syncs recent days; Microsoft Ads uses PascalCase columns.
  * Meta traffic arrives as utm_source facebook, fb, or ig; Microsoft lowercases
    campaign names in its UTMs.
  * One Meta ad set's ads still carry an old utm_content, so its spend and its
    sessions don't match until someone fixes the tag.
  * Platforms count more conversions than GA4 records key events.
  * Monthly budgets are set per campaign. In June, Meta retargeting is
    under-budgeted (over-pacing) and Microsoft brand is over-budgeted (under-pacing).

Output goes to data/ (git-ignored). Run:  python scripts/generate_data.py
"""

import csv
import json
import math
import random
import shutil
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

random.seed(7)
OUT = Path(__file__).resolve().parent.parent / "data"
ADS_START, END = date(2025, 10, 1), date(2026, 6, 18)  # ends mid-month, so June is still pacing
GA4_START = date(2026, 2, 2)

PLATFORMS = {
    # platform: utm_source choices (weighted), utm_medium, click->session rate, platform/GA4 conversion ratio
    "google_ads": ([("google", 1.0)], "cpc", 0.88, 1.15),
    "meta": ([("facebook", 0.7), ("ig", 0.25), ("fb", 0.05)], "paid_social", 0.72, 1.7),
    "microsoft_ads": ([("bing", 1.0)], "cpc", 0.85, 1.2),
}

# platform, campaign_id, campaign, ad_group_id, ad group, daily spend, CPM, CTR,
# lead rate per session, purchase rate per session, utm_content override
AD_GROUPS = [
    ("google_ads", "21001", "NW_Search_NonBrand", "31001", "Rain Jackets", 70, 95, .035, .040, .010, None),
    ("google_ads", "21001", "NW_Search_NonBrand", "31002", "Hiking Boots", 85, 90, .038, .045, .012, None),
    ("google_ads", "21001", "NW_Search_NonBrand", "31003", "Trail Packs", 45, 110, .030, .035, .006, None),
    ("google_ads", "21002", "NW_Search_Brand", "31004", "Brand Terms", 40, 60, .090, .090, .030, None),
    ("meta", "120210000000101", "NW_Prospecting_Lookalike", "120210000000201", "Lookalike_Video", 55, 9, .010, .012, .002, None),
    ("meta", "120210000000101", "NW_Prospecting_Lookalike", "120210000000202", "Lookalike_Carousel", 45, 10, .012, .014, .003,
     "Lookalike_Carousel_v1"),
    ("meta", "120210000000102", "NW_Retargeting_SiteVisitors", "120210000000203", "SiteVisitors_30d", 30, 16, .016, .035, .015, None),
    ("microsoft_ads", "418800301", "NW_Search_NonBrand", "518800401", "Rain Jackets", 30, 70, .040, .040, .010, None),
    ("microsoft_ads", "418800301", "NW_Search_NonBrand", "518800402", "Hiking Boots", 35, 65, .042, .042, .011, None),
    ("microsoft_ads", "418800302", "NW_Search_Brand", "518800403", "Brand Terms", 15, 45, .085, .085, .028, None),
]
SEASON = {1: .85, 2: .9, 3: 1.0, 4: 1.05, 5: 1.05, 6: .95, 7: .85, 8: .85, 9: 1.05, 10: 1.15, 11: 1.2, 12: .9}
WEEKDAY = [1.05, 1.1, 1.1, 1.05, 1.0, .75, .7]
ORGANIC = [(None, None), (None, None), (None, None), ("newsletter", "email")]  # mostly untagged visits


def noisy(x, sd=0.15):
    return x * math.exp(random.gauss(0, sd))


def poisson(lam):
    if lam <= 0:
        return 0
    n, p, l = 0, 1.0, math.exp(-lam)
    while True:
        p *= random.random()
        if p <= l:
            return n
        n += 1


def pick(weighted):
    r, acc = random.random(), 0.0
    for v, w in weighted:
        acc += w
        if r <= acc:
            return v
    return weighted[-1][0]


def airbyte_cols(extracted):
    return {"_airbyte_raw_id": str(uuid.UUID(int=random.getrandbits(128))),
            "_airbyte_extracted_at": extracted.isoformat(sep=" ")}


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"{path.relative_to(OUT.parent)}: {len(rows):,} rows")


class GA4Day:
    """Collects one day's GA4 export events."""

    def __init__(self, d):
        self.d, self.events = d, []

    def session(self, source, medium, campaign=None, content=None, leads=0, purchases=0):
        user = f"{random.randint(10**8, 10**9 - 1)}.{random.randint(10**9, 2 * 10**9)}"
        sid = random.randint(10**9, 2 * 10**9)
        t = datetime.combine(self.d, time(0), tzinfo=timezone.utc) + timedelta(seconds=random.randint(0, 86000))
        traffic = None
        if campaign:
            traffic = {"manual_source": source, "manual_medium": medium, "manual_campaign_name": campaign,
                       "manual_content": content, "manual_term": None, "manual_campaign_id": None, "gclid": None}
        names = ["session_start", "page_view"] + ["generate_lead"] * leads + ["purchase"] * purchases
        for i, name in enumerate(names):
            ts = t + timedelta(seconds=20 * i)
            ev = {
                "event_date": self.d.strftime("%Y%m%d"),
                "event_timestamp": int(ts.timestamp() * 1_000_000),
                "event_name": name,
                "event_params": [
                    {"key": "ga_session_id", "value": {"int_value": sid}},
                    {"key": "page_location", "value": {"string_value": "https://www.example.com/products"}},
                ],
                "user_pseudo_id": user,
                "platform": "WEB",
                # GA4 fills collected_traffic_source on the events that carry the UTMs.
                "collected_traffic_source": traffic if i < 2 else None,
                "ecommerce": None,
            }
            if name == "purchase":
                ev["ecommerce"] = {"purchase_revenue": round(noisy(180, 0.35), 2),
                                   "transaction_id": uuid.uuid4().hex[:12]}
            self.events.append(ev)

    def write(self):
        path = OUT / "ga4" / f"events_{self.d.strftime('%Y%m%d')}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for ev in self.events:
                f.write(json.dumps(ev) + "\n")
        return len(self.events)


def main():
    shutil.rmtree(OUT, ignore_errors=True)  # never mix files from an earlier run
    rows = {p: [] for p in PLATFORMS}
    ga4_events = 0
    d = ADS_START
    while d <= END:
        ga4 = GA4Day(d) if d >= GA4_START else None
        for (plat, cid, camp, agid, ag, base, cpm, ctr, lead_r, buy_r, utm_override) in AD_GROUPS:
            sources, medium, land, conv_ratio = PLATFORMS[plat]
            spend = round(noisy(base * SEASON[d.month] * WEEKDAY[d.weekday()]), 2)
            impressions = max(1, int(noisy(spend / cpm * 1000, 0.1)))
            clicks = min(impressions, int(round(noisy(impressions * ctr, 0.12))))
            sessions = min(clicks, int(round(clicks * noisy(land, 0.05))))
            key_events, revenue_proxy = 0, 0.0
            utm_campaign = camp.lower() if plat == "microsoft_ads" else camp
            utm_content = utm_override or ag
            for _ in range(sessions):
                leads = 1 if random.random() < lead_r else 0
                buys = 1 if random.random() < buy_r else 0
                key_events += leads + buys
                revenue_proxy += buys * 180
                if ga4:
                    ga4.session(pick(sources), medium, utm_campaign, utm_content, leads, buys)
            conversions = round(key_events * noisy(conv_ratio, 0.2), 1)
            value = round(revenue_proxy * noisy(1.1, 0.15), 2)
            rows[plat].append(dict(d=d, cid=cid, camp=camp, agid=agid, ag=ag, impressions=impressions,
                                   clicks=clicks, spend=spend, conv=conversions, value=value))
        if ga4:
            for _ in range(int(noisy(120, 0.2))):  # unpaid traffic the models should ignore
                src, med = random.choice(ORGANIC)
                ga4.session(src, med, "spring_newsletter" if src else None, None,
                            1 if random.random() < .02 else 0, 1 if random.random() < .006 else 0)
            ga4_events += ga4.write()
        d += timedelta(days=1)

    def synced(day, hour):
        return datetime.combine(day + timedelta(days=1), time(hour))

    write_csv(OUT / "raw_google_ads" / "ad_group_performance.csv", [
        {**airbyte_cols(synced(r["d"], 5)), "segments_date": r["d"].isoformat(),
         "campaign_id": r["cid"], "campaign_name": r["camp"], "ad_group_id": r["agid"],
         "ad_group_name": r["ag"], "metrics_impressions": r["impressions"], "metrics_clicks": r["clicks"],
         "metrics_cost_micros": int(round(r["spend"] * 1_000_000)), "metrics_conversions": r["conv"],
         "metrics_conversions_value": r["value"]} for r in rows["google_ads"]])

    meta = []
    for r in rows["meta"]:
        final = {"date_start": r["d"].isoformat(), "campaign_id": r["cid"], "campaign_name": r["camp"],
                 "adset_id": r["agid"], "adset_name": r["ag"], "impressions": r["impressions"],
                 "inline_link_clicks": r["clicks"], "spend": f"{r['spend']:.2f}",
                 "conversions": r["conv"], "conversion_value": f"{r['value']:.2f}"}
        if random.random() < 0.06:  # re-synced day: an early pull, then restated numbers
            early = dict(final, spend=f"{r['spend'] * 0.96:.2f}", conversions=max(0, r["conv"] - 1))
            meta.append({**airbyte_cols(synced(r["d"], 6)), **early})
            meta.append({**airbyte_cols(synced(r["d"], 6) + timedelta(days=2)), **final})
        else:
            meta.append({**airbyte_cols(synced(r["d"], 6)), **final})
    write_csv(OUT / "raw_meta_ads" / "ads_insights.csv", meta)

    write_csv(OUT / "raw_microsoft_ads" / "ad_group_performance_report_daily.csv", [
        {**airbyte_cols(synced(r["d"], 7)), "TimePeriod": r["d"].isoformat(), "CampaignId": r["cid"],
         "CampaignName": r["camp"], "AdGroupId": r["agid"], "AdGroupName": r["ag"],
         "Impressions": r["impressions"], "Clicks": r["clicks"], "Spend": r["spend"],
         "Conversions": r["conv"], "Revenue": r["value"]} for r in rows["microsoft_ads"]])

    # Monthly budgets per campaign: planned spend with some planning error.
    june_factor = {"120210000000102": 0.75, "418800302": 1.5}
    budgets, months = [], sorted({(r["d"].year, r["d"].month) for rs in rows.values() for r in rs})
    for plat, rs in rows.items():
        for cid in sorted({r["cid"] for r in rs}):
            name = next(r["camp"] for r in rs if r["cid"] == cid)
            groups = [g for g in AD_GROUPS if g[1] == cid]
            for y, m in months:
                first = date(y, m, 1)
                days_in_month = ((first.replace(day=28) + timedelta(days=4)).replace(day=1) - first).days
                planned = sum(g[5] for g in groups) * SEASON[m] * 0.96 * days_in_month
                factor = june_factor.get(cid, 1.0) if (y, m) == (2026, 6) else noisy(1.0, 0.06)
                budgets.append({"month": first.isoformat(), "platform": plat, "campaign_id": cid,
                                "campaign_name": name, "budget": round(planned * factor / 100) * 100})
    write_csv(OUT / "raw_planning" / "monthly_budgets.csv", budgets)

    print(f"data/ga4/: {ga4_events:,} events across {(END - GA4_START).days + 1} daily tables")


if __name__ == "__main__":
    main()
