import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReviewerGroupingBundle } from "../api/types";
import {
  OTHER_DOCUMENT_MESSAGE,
  UNLOCATABLE_MESSAGE,
  describeGroundedIn,
  evidenceLocationNotice,
  type EvidenceWindow,
} from "./groundedIn";
import { WorkspaceSourcePane } from "./WorkspaceSourcePane";

const PRIMARY = "a".repeat(64);
const OTHER = "b".repeat(64);

function window(
  overrides: Partial<EvidenceWindow> & Pick<EvidenceWindow, "anchor_status">,
): EvidenceWindow {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    kind: "dom",
    snippet: "[2016] SGHC 100",
    line_start: null,
    line_end: null,
    char_start: null,
    char_end: null,
    source_sha256: OTHER,
    grounded_in: null,
    ...overrides,
  };
}

const sourceRender: ReviewerGroupingBundle["source_render"] = {
  source_snapshot_id: "00000000-0000-0000-0000-00000000000a",
  render_mode: "safe_text",
  content: "The appeal against the decision below is dismissed.",
  anchors: [],
  truncated: false,
  omitted_anchor_count: 0,
};

function renderPane(
  reason: string | null,
  windows: EvidenceWindow[],
  render_override: Partial<ReviewerGroupingBundle["source_render"]> = {},
) {
  return render(
    <WorkspaceSourcePane
      caseTitle="A v B"
      sourceRender={{ ...sourceRender, ...render_override }}
      activeItem={{
        review_unit_id: "00000000-0000-0000-0000-0000000000ab",
        source_anchor_id: null,
        source_anchor_unavailable_reason: reason,
        evidence_windows: windows,
      }}
      documentHtml={null}
      htmlLoading={false}
      artifactAnchorUnavailable={false}
      view="text"
      onViewChange={() => undefined}
    />,
  );
}

describe("evidence location notice", () => {
  it("names other-document evidence by the member citation when the payload carries one", () => {
    const notice = evidenceLocationNotice("other_document", [
      window({
        anchor_status: "other_document",
        grounded_in: {
          source_sha256: OTHER,
          source_system: "sample_b",
          citation: "[2019] SGCA 1",
        },
      }),
    ]);
    expect(notice).toEqual({
      kind: "other_document",
      message: OTHER_DOCUMENT_MESSAGE,
      recordedIn: "[2019] SGCA 1",
    });
  });

  it("falls back to a shortened document hash without a collection label", () => {
    expect(
      describeGroundedIn({ source_sha256: OTHER, source_system: "sample_b", citation: null }),
    ).toBe("Document bbbbbbbbbbbb");
    expect(describeGroundedIn({ source_sha256: OTHER, source_system: null, citation: null })).toBe(
      "Document bbbbbbbbbbbb",
    );
    expect(describeGroundedIn(null)).toBeNull();
  });

  it("keeps the existing honest message for genuinely unresolved, missing and truncated states", () => {
    for (const reason of ["anchor_unresolved", "no_evidence", "source_truncated", null]) {
      const notice = evidenceLocationNotice(reason, [
        window({ anchor_status: "unexpected_unresolved", source_sha256: PRIMARY }),
      ]);
      expect(notice).toEqual({ kind: "unlocatable", message: UNLOCATABLE_MESSAGE });
    }
  });
});

describe("WorkspaceSourcePane evidence location", () => {
  it("shows the other-document message with the recorded citation", () => {
    renderPane("other_document", [
      window({
        anchor_status: "other_document",
        grounded_in: { source_sha256: OTHER, source_system: "sample_a", citation: "[2019] SGCA 1" },
      }),
    ]);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("data-evidence-location", "other_document");
    expect(status).toHaveTextContent(OTHER_DOCUMENT_MESSAGE);
    expect(status).toHaveTextContent("Recorded in [2019] SGCA 1.");
    expect(status).not.toHaveTextContent(UNLOCATABLE_MESSAGE);
  });

  it("shows the other-document message with source system and hash when no citation is known", () => {
    renderPane("other_document", [
      window({
        anchor_status: "other_document",
        grounded_in: { source_sha256: OTHER, source_system: "sample_b", citation: null },
      }),
    ]);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(OTHER_DOCUMENT_MESSAGE);
    expect(status).toHaveTextContent("Recorded in Document bbbbbbbbbbbb.");
    expect(status).not.toHaveTextContent(UNLOCATABLE_MESSAGE);
  });

  it("keeps the unlocatable message for a genuinely unresolved anchor", () => {
    renderPane("anchor_unresolved", [
      window({ anchor_status: "unexpected_unresolved", source_sha256: PRIMARY }),
    ]);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("data-evidence-location", "unlocatable");
    expect(status).toHaveTextContent(UNLOCATABLE_MESSAGE);
    expect(status).not.toHaveTextContent(OTHER_DOCUMENT_MESSAGE);
  });

  it("keeps the unlocatable message for evidence beyond the truncated render", () => {
    renderPane(
      "source_truncated",
      [
        window({
          anchor_status: "anchored",
          source_sha256: PRIMARY,
          char_start: 900000,
          char_end: 900015,
        }),
      ],
      { truncated: true, omitted_anchor_count: 1 },
    );
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(UNLOCATABLE_MESSAGE);
    expect(status).not.toHaveTextContent(OTHER_DOCUMENT_MESSAGE);
  });

  it("never renders an internal case identifier", () => {
    const payload: EvidenceWindow = window({
      anchor_status: "other_document",
      grounded_in: { source_sha256: OTHER, source_system: "sample_a", citation: null },
    });
    expect(JSON.stringify(payload)).not.toMatch(/CAS-\d/);
    expect("case_external_id" in (payload.grounded_in ?? {})).toBe(false);
    const { container } = renderPane("other_document", [payload]);
    expect(container.textContent).not.toMatch(/CAS-\d/);
  });
});
