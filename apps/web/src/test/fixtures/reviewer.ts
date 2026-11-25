import type {
  ReviewQueuePage,
  ReviewerGroupingBundle,
  SourceRenderArtifactMetadata,
} from "../../api/types";

export const demoTenantId = "00000000-0000-4000-8000-000000000010";
export const demoAssignmentId = "00000000-0000-4000-8000-000000000101";

const demoSource = `Review Platform synthetic source

Singapore Management University School of Law

In Public Prosecutor v Tan Wei Ming [2017] SGHC 12, the court considered whether the accused had acted with the required intention.

The judgment records the decision date as 14 February 2017. The coram was Justice A. Rahman. The neutral citation appears in the header as [2017] SGHC 12.

The court referred to Lee v Public Prosecutor [2015] SGCA 3 and Ng v Comptroller [2012] SGHC 44. These cited authorities were discussed in the section on evidential reliability.

This synthetic document is safe text only. It contains no raw paths, no source-system internals, no peer answers, and no validator rationale.`;

// A reviewer-safe sanitized document body, modelling what the backend source-render artifact
// endpoint delivers as `text/html`. It carries only inline styling: no scripts, no event handlers,
// no off-origin resources. Rendered inside a locked-down sandbox iframe in the source pane.
export const syntheticSourceHtml = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <style>
      body { font-family: Georgia, "Times New Roman", serif; color: #1b2432; line-height: 1.6; margin: 0; padding: 20px; }
      h1 { font-size: 1.1rem; margin: 0 0 4px; }
      .cite { color: #0f4c81; font-weight: 600; }
      mark { background: #ffe39a; padding: 0 2px; }
      .meta { color: #55617a; font-size: 0.85rem; margin-bottom: 16px; }
    </style>
  </head>
  <body>
    <h1>Public Prosecutor v Tan Wei Ming</h1>
    <p class="meta">Neutral citation <span class="cite">[2017] SGHC 12</span> &middot; Decision date 14 February 2017 &middot; Coram Justice A. Rahman</p>
    <p>The court considered whether the accused had acted with the required intention. The judgment records the decision date as <mark>14 February 2017</mark>.</p>
    <p>The court referred to <span class="cite">Lee v Public Prosecutor [2015] SGCA 3</span> and <span class="cite">Ng v Comptroller [2012] SGHC 44</span>. These cited authorities were discussed in the section on evidential reliability.</p>
    <p>This synthetic document is reviewer-safe. It contains no raw paths, no source-system internals, no peer answers, and no validator rationale.</p>
  </body>
</html>`;

export const syntheticSourceMetadata: SourceRenderArtifactMetadata = {
  schema_version: "source-render-artifact/v1",
  render_artifact_id: "00000000-0000-4000-8000-000000000601",
  source_snapshot_id: "00000000-0000-4000-8000-000000000501",
  subject_kind: "case",
  source_kind: "judgment",
  render_profile: "synthetic-demo",
  render_version: 1,
  render_mode: "sanitized_html",
  content_digest: "synthetic-content-digest",
  anchor_map_digest: "synthetic-anchor-digest",
  artifact_mime_type: "text/html",
  artifact_size_bytes: syntheticSourceHtml.length,
  body_url: `/tenants/${demoTenantId}/review/assignments/${demoAssignmentId}/source-render/body`,
  anchor_map_url: `/tenants/${demoTenantId}/review/assignments/${demoAssignmentId}/source-render/anchors`,
};

export const syntheticQueue: ReviewQueuePage = {
  items: [
    {
      review_unit_id: "00000000-0000-4000-8000-000000000201",
      assignment_id: demoAssignmentId,
      campaign_id: "00000000-0000-4000-8000-000000000001",
      case_id: "CASE000000000001",
      subject_kind: "case",
      review_kind: "value_provenance",
      display_title: "Public Prosecutor v Tan Wei Ming",
      display_subtitle: "[2017] SGHC 12",
      safe_field_label: "Grouped case fields",
      assignment_status: "assigned",
    },
  ],
  has_more: false,
  next_cursor: null,
};

export const syntheticBundle: ReviewerGroupingBundle = {
  case_submitted: false,
  schema_version: "reviewer-grouping-bundle/v1",
  allowed_actions: ["save_draft", "submit"],
  lock_version: 1,
  case_header: {
    subject_id: "00000000-0000-4000-8000-000000000301",
    subject_kind: "case",
    case_title: "Public Prosecutor v Tan Wei Ming",
    case_identifier_display: "Synthetic case SRP-001",
    neutral_citation_display: "[2017] SGHC 12",
    campaign_name: "Demo Workspace synthetic reviewer campaign",
  },
  field_groups: [
    {
      group_id: "case_metadata",
      group_label: "Case metadata",
      group_kind: "atomic",
      order: 1,
      item_count: 3,
      completed_count: 0,
      description: "Core case facts extracted from the judgment header.",
      group_anchor_id: "anchor-metadata",
      items: [
        {
          review_unit_id: "00000000-0000-4000-8000-000000000201",
          assignment_id: demoAssignmentId,
          item_id: "neutral_citation",
          item_label: "Neutral citation",
          item_kind: "field",
          member_values: [],
          cross_source_disagreement: false,
          extraction_state: "present",
          extracted_value_display: "[2017] SGHC 12",
          evidence_window_ids: ["00000000-0000-4000-8000-000000000401"],
          status: "not_started",
          lock_version: 1,
          source_anchor_id: "anchor-neutral-citation",
          source_anchor_unavailable_reason: null,
          ordinal: null,
          extracted_value_raw: "[2017] SGHC 12",
          normalized_value: "[2017] SGHC 12",
          answer_summary: null,
        },
        {
          review_unit_id: "00000000-0000-4000-8000-000000000202",
          assignment_id: demoAssignmentId,
          item_id: "decision_date",
          item_label: "Decision date",
          item_kind: "field",
          member_values: [],
          cross_source_disagreement: false,
          extraction_state: "present",
          extracted_value_display: "14 February 2017",
          evidence_window_ids: ["00000000-0000-4000-8000-000000000402"],
          status: "not_started",
          lock_version: 1,
          source_anchor_id: "anchor-date",
          source_anchor_unavailable_reason: null,
          ordinal: null,
          extracted_value_raw: "2017-02-14",
          normalized_value: "2017-02-14",
          answer_summary: null,
        },
        {
          review_unit_id: "00000000-0000-4000-8000-000000000203",
          assignment_id: demoAssignmentId,
          item_id: "coram",
          item_label: "Coram",
          item_kind: "field",
          member_values: [],
          cross_source_disagreement: false,
          extraction_state: "present",
          extracted_value_display: "Justice A. Rahman",
          evidence_window_ids: ["00000000-0000-4000-8000-000000000403"],
          status: "not_started",
          lock_version: 1,
          source_anchor_id: "anchor-coram",
          source_anchor_unavailable_reason: null,
          ordinal: null,
          extracted_value_raw: "Justice A. Rahman",
          normalized_value: "Justice A. Rahman",
          answer_summary: null,
        },
      ],
    },
    {
      group_id: "cited_cases",
      group_label: "Cited cases",
      group_kind: "non_atomic",
      order: 2,
      item_count: 2,
      completed_count: 0,
      description: "Authorities cited in the judgment.",
      group_anchor_id: "anchor-citations",
      items: [
        {
          review_unit_id: "00000000-0000-4000-8000-000000000204",
          assignment_id: demoAssignmentId,
          item_id: "cited_case_1",
          item_label: "Lee v Public Prosecutor",
          item_kind: "relation",
          member_values: [],
          cross_source_disagreement: false,
          ordinal: 1,
          extraction_state: "present",
          extracted_value_display: "Lee v Public Prosecutor [2015] SGCA 3",
          evidence_window_ids: ["00000000-0000-4000-8000-000000000404"],
          status: "not_started",
          lock_version: 1,
          source_anchor_id: "anchor-cited-lee",
          source_anchor_unavailable_reason: null,
          extracted_value_raw: "Lee v Public Prosecutor [2015] SGCA 3",
          normalized_value: "Lee v Public Prosecutor [2015] SGCA 3",
          answer_summary: null,
        },
        {
          review_unit_id: "00000000-0000-4000-8000-000000000205",
          assignment_id: demoAssignmentId,
          item_id: "cited_case_2",
          item_label: "Ng v Comptroller",
          item_kind: "relation",
          member_values: [],
          cross_source_disagreement: false,
          ordinal: 2,
          extraction_state: "present",
          extracted_value_display: "Ng v Comptroller [2012] SGHC 44",
          evidence_window_ids: ["00000000-0000-4000-8000-000000000405"],
          status: "not_started",
          lock_version: 1,
          source_anchor_id: "anchor-cited-ng",
          source_anchor_unavailable_reason: null,
          extracted_value_raw: "Ng v Comptroller [2012] SGHC 44",
          normalized_value: "Ng v Comptroller [2012] SGHC 44",
          answer_summary: null,
        },
      ],
    },
  ],
  progress: {
    total_items: 5,
    completed_items: 0,
    remaining_items: 5,
    group_progress: [
      { group_id: "case_metadata", completed_count: 0, item_count: 3 },
      { group_id: "cited_cases", completed_count: 0, item_count: 2 },
    ],
  },
  source_render: {
    source_snapshot_id: "00000000-0000-4000-8000-000000000501",
    render_mode: "safe_text",
    content: demoSource,
    truncated: false,
    omitted_anchor_count: 0,
    anchors: [
      {
        anchor_id: "anchor-metadata",
        group_id: "case_metadata",
        item_id: null,
        review_unit_id: null,
        char_start: demoSource.indexOf("In Public Prosecutor"),
        char_end: demoSource.indexOf("In Public Prosecutor") + 70,
        label: "Case metadata",
        line_start: null,
        line_end: null,
        scroll_hint: "start",
      },
      {
        anchor_id: "anchor-neutral-citation",
        group_id: "case_metadata",
        item_id: "neutral_citation",
        review_unit_id: "00000000-0000-4000-8000-000000000201",
        char_start: demoSource.indexOf("[2017] SGHC 12"),
        char_end: demoSource.indexOf("[2017] SGHC 12") + "[2017] SGHC 12".length,
        label: "Neutral citation",
        line_start: null,
        line_end: null,
        scroll_hint: "center",
      },
      {
        anchor_id: "anchor-date",
        group_id: "case_metadata",
        item_id: "decision_date",
        review_unit_id: "00000000-0000-4000-8000-000000000202",
        char_start: demoSource.indexOf("14 February 2017"),
        char_end: demoSource.indexOf("14 February 2017") + "14 February 2017".length,
        label: "Decision date",
        line_start: null,
        line_end: null,
        scroll_hint: "center",
      },
      {
        anchor_id: "anchor-coram",
        group_id: "case_metadata",
        item_id: "coram",
        review_unit_id: "00000000-0000-4000-8000-000000000203",
        char_start: demoSource.indexOf("Justice A. Rahman"),
        char_end: demoSource.indexOf("Justice A. Rahman") + "Justice A. Rahman".length,
        label: "Coram",
        line_start: null,
        line_end: null,
        scroll_hint: "center",
      },
      {
        anchor_id: "anchor-citations",
        group_id: "cited_cases",
        item_id: null,
        review_unit_id: null,
        char_start: demoSource.indexOf("The court referred"),
        char_end: demoSource.indexOf("The court referred") + 110,
        label: "Cited cases",
        line_start: null,
        line_end: null,
        scroll_hint: "start",
      },
      {
        anchor_id: "anchor-cited-lee",
        group_id: "cited_cases",
        item_id: "cited_case_1",
        review_unit_id: "00000000-0000-4000-8000-000000000204",
        char_start: demoSource.indexOf("Lee v Public Prosecutor"),
        char_end:
          demoSource.indexOf("Lee v Public Prosecutor") +
          "Lee v Public Prosecutor [2015] SGCA 3".length,
        label: "Lee v Public Prosecutor",
        line_start: null,
        line_end: null,
        scroll_hint: "center",
      },
      {
        anchor_id: "anchor-cited-ng",
        group_id: "cited_cases",
        item_id: "cited_case_2",
        review_unit_id: "00000000-0000-4000-8000-000000000205",
        char_start: demoSource.indexOf("Ng v Comptroller"),
        char_end: demoSource.indexOf("Ng v Comptroller") + "Ng v Comptroller [2012] SGHC 44".length,
        label: "Ng v Comptroller",
        line_start: null,
        line_end: null,
        scroll_hint: "center",
      },
    ],
  },
};
