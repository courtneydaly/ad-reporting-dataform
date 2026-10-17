"""Load the generated raw data into BigQuery, the way the real sources land it.

Creates raw_google_ads, raw_meta_ads, raw_microsoft_ads, raw_planning, and a GA4-style
analytics_123456789 dataset with one events_YYYYMMDD table per day.

Run after scripts/generate_data.py:
    pip install google-cloud-bigquery
    gcloud auth application-default login
    python scripts/load_to_bigquery.py --project your-gcp-project-id
"""

import argparse
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
GA4_DATASET = "analytics_123456789"  # keep in sync with vars.ga4_dataset in workflow_settings.yaml

AIRBYTE = [("_airbyte_raw_id", "STRING"), ("_airbyte_extracted_at", "TIMESTAMP")]

# Raw column types, chosen to match what each source actually sends.
CSV_TABLES = {
    ("raw_google_ads", "ad_group_performance"): AIRBYTE + [
        ("segments_date", "STRING"), ("campaign_id", "INT64"), ("campaign_name", "STRING"),
        ("ad_group_id", "INT64"), ("ad_group_name", "STRING"), ("metrics_impressions", "INT64"),
        ("metrics_clicks", "INT64"), ("metrics_cost_micros", "INT64"),
        ("metrics_conversions", "FLOAT64"), ("metrics_conversions_value", "FLOAT64"),
    ],
    ("raw_meta_ads", "ads_insights"): AIRBYTE + [
        ("date_start", "STRING"), ("campaign_id", "STRING"), ("campaign_name", "STRING"),
        ("adset_id", "STRING"), ("adset_name", "STRING"), ("impressions", "INT64"),
        ("inline_link_clicks", "INT64"), ("spend", "STRING"), ("conversions", "FLOAT64"),
        ("conversion_value", "STRING"),
    ],
    ("raw_microsoft_ads", "ad_group_performance_report_daily"): AIRBYTE + [
        ("TimePeriod", "STRING"), ("CampaignId", "INT64"), ("CampaignName", "STRING"),
        ("AdGroupId", "INT64"), ("AdGroupName", "STRING"), ("Impressions", "INT64"),
        ("Clicks", "INT64"), ("Spend", "FLOAT64"), ("Conversions", "FLOAT64"), ("Revenue", "FLOAT64"),
    ],
    # In practice a planning Google Sheet connected to BigQuery as an external table.
    ("raw_planning", "monthly_budgets"): [
        ("month", "DATE"), ("platform", "STRING"), ("campaign_id", "STRING"),
        ("campaign_name", "STRING"), ("budget", "FLOAT64"),
    ],
}


def ga4_schema(bigquery):
    F = bigquery.SchemaField
    return [
        F("event_date", "STRING"),
        F("event_timestamp", "INT64"),
        F("event_name", "STRING"),
        F("event_params", "RECORD", mode="REPEATED", fields=[
            F("key", "STRING"),
            F("value", "RECORD", fields=[
                F("string_value", "STRING"), F("int_value", "INT64"),
                F("float_value", "FLOAT64"), F("double_value", "FLOAT64"),
            ]),
        ]),
        F("user_pseudo_id", "STRING"),
        F("platform", "STRING"),
        F("collected_traffic_source", "RECORD", fields=[
            F("manual_campaign_id", "STRING"), F("manual_campaign_name", "STRING"),
            F("manual_source", "STRING"), F("manual_medium", "STRING"),
            F("manual_term", "STRING"), F("manual_content", "STRING"), F("gclid", "STRING"),
        ]),
        F("ecommerce", "RECORD", fields=[
            F("purchase_revenue", "FLOAT64"), F("transaction_id", "STRING"),
        ]),
    ]


def main():
    from google.cloud import bigquery

    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="US")
    args = parser.parse_args()
    client = bigquery.Client(project=args.project, location=args.location)

    for dataset in {d for d, _ in CSV_TABLES} | {GA4_DATASET}:
        client.create_dataset(f"{args.project}.{dataset}", exists_ok=True)

    for (dataset, table), cols in CSV_TABLES.items():
        job = client.load_table_from_file(
            open(DATA / dataset / f"{table}.csv", "rb"),
            f"{args.project}.{dataset}.{table}",
            job_config=bigquery.LoadJobConfig(
                source_format="CSV", skip_leading_rows=1, write_disposition="WRITE_TRUNCATE",
                schema=[bigquery.SchemaField(n, t) for n, t in cols],
            ),
        )
        job.result()
        print(f"{dataset}.{table}: {job.output_rows:,} rows")

    files = sorted((DATA / "ga4").glob("events_*.jsonl"))
    for path in files:
        client.load_table_from_file(
            open(path, "rb"),
            f"{args.project}.{GA4_DATASET}.{path.stem}",
            job_config=bigquery.LoadJobConfig(
                source_format="NEWLINE_DELIMITED_JSON", write_disposition="WRITE_TRUNCATE",
                schema=ga4_schema(bigquery),
            ),
        ).result()
    print(f"{GA4_DATASET}: {len(files)} daily events tables")


if __name__ == "__main__":
    main()
