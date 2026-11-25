import { readFileSync } from "node:fs";
import path from "node:path";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { syntheticBundle } from "../../test/fixtures/reviewer";
import { SourcePane } from "./ReviewerWorkspacePanes";
import { emptyAnswer } from "./reviewerAnswerState";
import { newProposal, proposalItem } from "./reviewerProposals";

// Pins the reviewer workspace page's default `sourceView` state to "text" so a case/assignment
// always opens in Text mode (Document stays one click away via the segmented control), even when a
// sanitized document artifact is available. `SourcePane` itself only receives `view` as a prop --
// the state that decides the *initial* value lives one level up in `ReviewerWorkspacePage`, so a
// prop-level render of `SourcePane` alone cannot exercise that default. Mounting the full page
// requires router/query-client/auth-session providers uninvolved in this defect, so this asserts
// directly against the state initializer instead of duplicating that scaffolding.
describe("ReviewerWorkspacePage source view default", () => {
  it('initializes sourceView to "text", not "document"', () => {
    const source = readFileSync(path.join(__dirname, "ReviewerWorkspacePage.tsx"), "utf-8");
    expect(source).toMatch(/const \[sourceView, setSourceView\] = useState<SourceView>\("text"\)/);
  });
});

// Regression coverage for the Text-mode "small highlighted box, then a huge blank area" defect.
//
// Root cause (see styles.css `.source-pane` comment): the pane used a 4-row CSS grid template but
// only ever rendered 2-6 direct children depending on which notices were conditionally present.
// When the scrollable content (<pre>) landed on an "auto" row instead of the intended
// `minmax(360px, 1fr)` row, it collapsed to near-zero height (browsers give overflow:auto grid
// items a zero automatic minimum size), while the reserved 1fr row sat empty below it. The fix
// wraps every notice plus the Document/Text content in one always-present `.source-body` flex
// container, so `.source-pane` always has exactly two children and the row template can't
// mismatch. These tests exercise the React output (unaffected by jsdom's lack of real CSS layout)
// to prove the surrounding text is still in the DOM and that active-anchor scrolling targets the
// pane's own container rather than window/ancestor scrollIntoView.
describe("SourcePane (Text mode)", () => {
  afterEach(() => {
    cleanup();
  });

  const noop = () => {};

  function renderTextMode(overrides: Partial<Parameters<typeof SourcePane>[0]> = {}) {
    const activeItem = syntheticBundle.field_groups[0].items[0]; // neutral_citation
    return render(
      <SourcePane
        bundle={syntheticBundle}
        activeItem={activeItem}
        activeAnswer={undefined}
        artifactAnchorUnavailable={false}
        documentHtml={null}
        htmlLoading={false}
        view="text"
        onViewChange={noop}
        pickingProvenance={false}
        onProvenancePick={noop}
        {...overrides}
      />,
    );
  }

  it("lets the switch control group highlights while adding and resets it outside Cited cases", () => {
    const group = syntheticBundle.field_groups.find((g) => g.group_id === "cited_cases")!;
    const item = proposalItem(newProposal(group), "assignment");
    const version = "a".repeat(64);
    const snapshot = syntheticBundle.source_render.source_snapshot_id;
    const props: Parameters<typeof SourcePane>[0] = {
      bundle: {
        ...syntheticBundle,
        proposal_source_version: version,
        field_groups: [
          ...syntheticBundle.field_groups.filter((g) => g !== group),
          { ...group, items: [...group.items, item] },
        ],
        provenance_context: [
          {
            item_id: group.items[0].review_unit_id,
            group_id: "cited_cases",
            kind: "Extracted",
            value: "Known citation",
            superseded: false,
            source_snapshot_id: snapshot,
            source_version: version,
            char_start: 0,
            char_end: 10,
          },
        ],
      },
      activeItem: item,
      activeAnswer: {
        ...emptyAnswer,
        corrected_provenance_spans: [
          {
            evidence_window_id: item.review_unit_id,
            source_snapshot_id: snapshot,
            source_version: version,
            char_start: 20,
            char_end: 30,
          },
        ],
      },
      artifactAnchorUnavailable: false,
      documentHtml: null,
      htmlLoading: false,
      view: "text",
      onViewChange: noop,
      pickingProvenance: false,
      onProvenancePick: noop,
    };
    const { container, rerender } = render(<SourcePane {...props} />);
    const known = () => container.querySelector('[data-highlight-owners*="Known citation"]');
    const toggle = screen.getByRole("switch", { name: "Show all citations" });
    expect(known()).toBeNull();
    expect(container.querySelector(".source-highlight-selected")).not.toBeNull();
    fireEvent.click(toggle);
    expect(known()).not.toBeNull();
    fireEvent.click(toggle);
    expect(known()).toBeNull();
    fireEvent.click(toggle);
    rerender(<SourcePane {...props} activeItem={syntheticBundle.field_groups[0].items[0]} />);
    expect(toggle).toBeDisabled();
    expect(toggle).toHaveAttribute("aria-checked", "false");
    rerender(<SourcePane {...props} />);
    expect(toggle).toBeEnabled();
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(known()).toBeNull();
  });

  it("renders the full document text, not just the highlighted anchor", () => {
    renderTextMode();

    const content = syntheticBundle.source_render.content;
    const pre = document.querySelector(".source-text");
    expect(pre).not.toBeNull();
    expect(pre?.textContent).toBe(content);

    // Explicitly assert text well before and well after the active anchor is present -- this is
    // what "only shows the highlighted snippet" would fail.
    expect(pre?.textContent).toContain("Review Platform synthetic source");
    expect(pre?.textContent).toContain("no validator rationale.");
  });

  it("highlights exactly the anchor's character range, no more and no less", () => {
    renderTextMode();

    const content = syntheticBundle.source_render.content;
    const anchor = syntheticBundle.source_render.anchors.find(
      (candidate) => candidate.anchor_id === "anchor-neutral-citation",
    );
    expect(anchor?.char_start).not.toBeNull();
    expect(anchor?.char_end).not.toBeNull();
    const expectedText = content.slice(anchor!.char_start as number, anchor!.char_end as number);

    const activeMark = document.querySelector('[data-active-anchor="true"]');
    expect(activeMark).not.toBeNull();
    expect(activeMark?.textContent).toBe(expectedText);
    expect(expectedText).toBe("[2017] SGHC 12");
  });

  it("keeps every conditional notice inside one always-present body container, so the scrollable pane never depends on how many notices are showing", () => {
    const { container: containerLoading } = renderTextMode({ htmlLoading: true });
    const bodyLoading = containerLoading.querySelector(".source-body");
    expect(bodyLoading).not.toBeNull();
    // Both the loading notice and the <pre> live inside the same body element.
    expect(bodyLoading?.querySelector(".notice")).not.toBeNull();
    expect(bodyLoading?.querySelector(".source-text")).not.toBeNull();
    cleanup();

    const { container: containerPlain } = renderTextMode();
    const bodyPlain = containerPlain.querySelector(".source-body");
    expect(bodyPlain).not.toBeNull();
    expect(bodyPlain?.querySelector(".notice")).toBeNull();
    expect(bodyPlain?.querySelector(".source-text")).not.toBeNull();

    // Whether or not a notice rendered, `.source-pane` itself always has exactly the heading plus
    // the one body wrapper as children -- the two rows the CSS grid template expects.
    const pane = containerPlain.querySelector(".source-pane");
    expect(pane?.children.length).toBe(2);
  });

  it("scrolls the pane's own text container on active-anchor change, not window or an ancestor via scrollIntoView", () => {
    const scrollToSpy = vi.fn();
    // jsdom does not implement scrollTo on elements by default.
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollToSpy,
    });
    const scrollIntoViewSpy = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoViewSpy,
    });

    const { rerender } = renderTextMode({
      activeItem: syntheticBundle.field_groups[0].items[0],
    });

    // Switching the active item re-runs the scroll effect.
    rerender(
      <SourcePane
        bundle={syntheticBundle}
        activeItem={syntheticBundle.field_groups[0].items[1]}
        activeAnswer={undefined}
        artifactAnchorUnavailable={false}
        documentHtml={null}
        htmlLoading={false}
        view="text"
        onViewChange={noop}
        pickingProvenance={false}
        onProvenancePick={noop}
      />,
    );

    expect(scrollToSpy).toHaveBeenCalled();
    // The call is on the <pre> container itself (this test's spy is on the shared prototype, so we
    // additionally confirm the app code never reaches for scrollIntoView on the highlighted node or
    // any ancestor -- the historical Safari/WebKit pitfall this fix avoids).
    expect(scrollIntoViewSpy).not.toHaveBeenCalled();

    Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
    Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  });

  it("preserves the reading position after removal and allows later navigation to scroll normally", () => {
    const scroll = vi.spyOn(Element.prototype, "scrollTo");
    const { rerender } = renderTextMode({ preserveScroll: true });
    expect(scroll).not.toHaveBeenCalled();
    rerender(
      <SourcePane
        bundle={syntheticBundle}
        activeItem={syntheticBundle.field_groups[0].items[0]}
        activeAnswer={undefined}
        artifactAnchorUnavailable={false}
        documentHtml={null}
        htmlLoading={false}
        view="text"
        onViewChange={noop}
        pickingProvenance={false}
        onProvenancePick={noop}
        preserveScroll={false}
      />,
    );
    expect(scroll).toHaveBeenCalledOnce();
  });

  it("exposes a keyboard-operable, accessibly-labelled expand control", () => {
    renderTextMode();

    const expandButton = screen.getByRole("button", { name: /expand source view/i });
    expect(expandButton).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(expandButton);
    const collapseButton = screen.getByRole("button", { name: /collapse source view/i });
    expect(collapseButton).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector(".source-pane.is-expanded")).not.toBeNull();
  });

  it.each([undefined, "sample_a", "sample_b", "other_source"])(
    "names the judgment pane without displaying case collection %s",
    (sourceSystem) => {
      renderTextMode({
        bundle: {
          ...syntheticBundle,
          case_header: { ...syntheticBundle.case_header, source_system: sourceSystem },
        },
      });

      const pane = screen.getByRole("complementary", { name: "Judgment" });
      expect(pane).toBeVisible();
      expect(pane).not.toHaveTextContent(/sample a|sample b|other_source/i);
      expect(pane.querySelector(".source-system-chip")).toBeNull();
    },
  );
});
