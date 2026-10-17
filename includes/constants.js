// Shared definitions used across models, so a rule only lives in one place.

// GA4 events that count as key events.
const KEY_EVENTS = ["generate_lead", "purchase"];

// How GA4 traffic sources map to the ad platform that paid for them.
// Meta traffic shows up under several utm_source values.
const PAID_TRAFFIC = [
  { platform: "google_ads", sources: ["google"], mediums: ["cpc"] },
  { platform: "meta", sources: ["facebook", "fb", "ig", "instagram"], mediums: ["paid_social"] },
  { platform: "microsoft_ads", sources: ["bing"], mediums: ["cpc"] },
];

const quoted = (values) => values.map((v) => `'${v}'`).join(", ");

// SQL CASE expression that returns the ad platform for a source/medium pair,
// or NULL for unpaid traffic.
function platformFromUtm(sourceCol, mediumCol) {
  const whens = PAID_TRAFFIC.map(
    (p) =>
      `WHEN LOWER(${sourceCol}) IN (${quoted(p.sources)}) ` +
      `AND LOWER(${mediumCol}) IN (${quoted(p.mediums)}) THEN '${p.platform}'`
  );
  return `CASE\n    ${whens.join("\n    ")}\n  END`;
}

// Join key for names that pass through UTMs: case and stray spaces vary by platform.
function joinKey(col) {
  return `LOWER(TRIM(${col}))`;
}

// A campaign is "on pace" when spend to date is within this share of where it should be.
const PACING_TOLERANCE = 0.1;

module.exports = { KEY_EVENTS, PAID_TRAFFIC, PACING_TOLERANCE, quoted, platformFromUtm, joinKey };
