// Raw tables as they land in BigQuery: ad platforms from Airbyte, plus the GA4 export.

declare({
  schema: "raw_google_ads",
  name: "ad_group_performance",
  description: "Google Ads ad group performance by day. Cost arrives in micros.",
});

declare({
  schema: "raw_meta_ads",
  name: "ads_insights",
  description: "Meta ad set insights by day. Airbyte re-syncs recent days, so a day can appear more than once.",
});

declare({
  schema: "raw_microsoft_ads",
  name: "ad_group_performance_report_daily",
  description: "Microsoft Ads ad group performance report by day, with PascalCase columns.",
});

declare({
  schema: "raw_planning",
  name: "monthly_budgets",
  description: "Monthly budget per campaign. In practice a planning Google Sheet connected to BigQuery as an external table.",
});

declare({
  schema: dataform.projectConfig.vars.ga4_dataset,
  name: "events_*",
  description: "GA4 BigQuery export, one events_YYYYMMDD table per day. Starts the day the export was linked.",
});
