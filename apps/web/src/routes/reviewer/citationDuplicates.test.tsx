import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../../api/client";
import { WorkspaceSourcePane } from "../../components/WorkspaceSourcePane";
import { syntheticBundle } from "../../test/fixtures/reviewer";
import { CitationDuplicateFeedback } from "./CitationDuplicateFeedback";
import { emptyAnswer } from "./reviewerAnswerState";
import { newProposal, proposalItem } from "./reviewerProposals";
import { reviewerContext } from "./reviewerProvenanceContext";
import { ProvenanceContextLegend } from "./ReviewerWorkspacePanes";
import { useCitationDuplicates, type DuplicateCheck } from "./useCitationDuplicates";

vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/client")>()),
  apiRequest: vi.fn(),
}));
const group = syntheticBundle.field_groups.find((g) => g.group_id === "cited_cases")!;
const proposal = newProposal(group);
const item = proposalItem(proposal, "assignment");
const answer = { ...emptyAnswer, corrected_value: "Citation A" };
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("duplicate feedback", () => {
  it.each(["cited_cases", "statutes_cited"])(
    "debounces %s value edits and automatically checks without saving",
    async (groupId) => {
      vi.useFakeTimers();
      const target = proposalItem({ ...proposal, group_id: groupId }, "assignment");
      vi.mocked(apiRequest).mockResolvedValue({ fingerprint: "a".repeat(64), conflicts: [] });
      const { result, rerender } = renderHook(
        ({ value }) =>
          useCitationDuplicates("tenant", target, { ...answer, corrected_value: value }, "csrf"),
        { initialProps: { value: "A" } },
      );
      rerender({ value: "B" });
      expect(apiRequest).not.toHaveBeenCalled();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(300);
      });
      expect(apiRequest).toHaveBeenCalledOnce();
      expect(result.current.data?.conflicts).toEqual([]);
      rerender({ value: "C" });
      expect(result.current.data).toBeUndefined();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(300);
      });
      expect(apiRequest).toHaveBeenCalledTimes(2);
    },
  );

  it("checks provenance-only drafts and rechecks when marks are replaced or cleared", async () => {
    vi.useFakeTimers();
    vi.mocked(apiRequest).mockResolvedValue({ fingerprint: "a", conflicts: [] });
    const marked = {
      evidence_window_id: "window",
      source_snapshot_id: "source",
      source_version: "a".repeat(64),
      char_start: 10,
      char_end: 30,
      selected_text: "Citation A",
    };
    const { rerender } = renderHook(
      ({ spans }) =>
        useCitationDuplicates(
          "tenant",
          item,
          { ...emptyAnswer, corrected_provenance_spans: spans },
          "csrf",
        ),
      { initialProps: { spans: [marked] } },
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(apiRequest).toHaveBeenCalledOnce();
    expect(vi.mocked(apiRequest).mock.calls[0][1]?.body).toMatchObject({
      value: "",
      provenance: [{ char_start: 10, char_end: 30 }],
    });
    rerender({ spans: [{ ...marked, char_start: 40, char_end: 60 }] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(apiRequest).toHaveBeenCalledTimes(2);
    rerender({ spans: [] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(apiRequest).toHaveBeenCalledTimes(2);
  });

  it("ignores late results from earlier actions", async () => {
    let oldResponse!: (v: DuplicateCheck) => void;
    vi.mocked(apiRequest).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          oldResponse = resolve;
        }),
    );
    vi.mocked(apiRequest).mockResolvedValueOnce({ fingerprint: "new", conflicts: [] });
    const { result } = renderHook(() => useCitationDuplicates("tenant", item, answer, "csrf"));
    let first!: Promise<void>;
    await act(async () => {
      first = result.current.check(item, answer);
      await result.current.check(item, answer);
      oldResponse({ fingerprint: "old", conflicts: [] });
      await first;
    });
    expect(result.current.data?.fingerprint).toBe("new");
  });

  it("shows conflicting items without an acknowledgement or success message", () => {
    const onOpen = vi.fn();
    const feedback = {
      enabled: true,
      error: undefined,
      check: vi.fn(),
      data: {
        fingerprint: "a",
        conflicts: [
          {
            item_id: "locked",
            value: "A",
            kind: "confirmed" as const,
            reason: "Same value and provenance",
            submitted: true,
          },
        ],
      },
    };
    const { rerender } = render(<CitationDuplicateFeedback onOpen={onOpen} feedback={feedback} />);
    expect(screen.getByText(/Duplication detected,/)).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Click here to view the existing citation: A" }),
    );
    expect(onOpen).toHaveBeenCalledWith("locked");
    expect(screen.queryByRole("textbox")).toBeNull();
    rerender(
      <CitationDuplicateFeedback
        onOpen={onOpen}
        feedback={{ ...feedback, data: { fingerprint: "b", conflicts: [] } }}
      />,
    );
    expect(screen.queryByText("No duplicate items found.")).toBeNull();
    expect(screen.queryByText(/Duplication detected/)).toBeNull();
  });
});

it("keeps group marks, source isolation, overlap associations and keyboard/click information", () => {
  const original = group.items[0];
  const version = "a".repeat(64),
    snapshot = syntheticBundle.source_render.source_snapshot_id;
  const context = {
    item_id: original.review_unit_id,
    group_id: group.group_id,
    value: "Existing citation",
    kind: "Extracted" as const,
    superseded: false,
    source_snapshot_id: snapshot,
    source_version: version,
    char_start: 0,
    char_end: 10,
  };
  const bundle = {
    ...syntheticBundle,
    proposal_source_version: version,
    field_groups: [{ ...group, items: [original, item] }],
    provenance_context: [
      context,
      { ...context, kind: "Your correction" as const, char_start: 5, char_end: 15 },
      { ...context, value: "FOREIGN", source_version: "b".repeat(64) },
    ],
  };
  const marks = reviewerContext(bundle, item, {
    [original.review_unit_id]: { ...emptyAnswer, saved: true, provenance_correct: false },
  });
  expect(marks).toHaveLength(2);
  expect(marks[0].className).toContain("superseded");
  const open = vi.fn();
  const { container } = render(
    <WorkspaceSourcePane
      caseTitle="Case"
      sourceRender={bundle.source_render}
      activeItem={null}
      documentHtml={null}
      htmlLoading={false}
      artifactAnchorUnavailable={false}
      view="text"
      onViewChange={vi.fn()}
      contextMarks={marks}
      contextLegend={<ProvenanceContextLegend marks={marks} onOpen={open} />}
    />,
  );
  const overlap = [...container.querySelectorAll("mark")].find(
    (m) =>
      m.getAttribute("aria-label")?.includes("Your correction") &&
      m.getAttribute("aria-label")?.includes("Extracted"),
  )!;
  expect(overlap).toHaveAttribute("tabindex", "0");
  fireEvent.focus(overlap);
  expect(screen.getByRole("tooltip")).toHaveTextContent("incorrect or superseded");
  fireEvent.blur(overlap);
  fireEvent.click(overlap);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Your correction");
  expect(open).not.toHaveBeenCalled();
  expect(container.textContent).not.toContain("FOREIGN");
  expect(
    container
      .querySelector(".source-body")
      ?.contains(container.querySelector(".provenance-context-legend")),
  ).toBe(true);
});
