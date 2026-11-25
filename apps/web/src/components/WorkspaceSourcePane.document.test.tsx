import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { syntheticBundle } from "../test/fixtures/reviewer";
import { WorkspaceSourcePane } from "./WorkspaceSourcePane";

afterEach(cleanup);

it("shows an inert, unhighlighted document and retains Text highlights", () => {
  const group = syntheticBundle.field_groups.find((item) => item.group_id === "cited_cases")!;
  const activeItem = group.items[0];
  const onAddCitation = vi.fn();
  const onProvenancePick = vi.fn();
  const html = "<p>Formatted judgment with a cited case.</p>";
  const props = {
    caseTitle: "Example judgment",
    sourceRender: syntheticBundle.source_render,
    activeItem,
    documentHtml: html,
    htmlLoading: false,
    artifactAnchorUnavailable: false,
    onViewChange: vi.fn(),
    onAddCitation,
    onProvenancePick,
  };
  const { container, rerender } = render(<WorkspaceSourcePane {...props} view="document" />);
  const frame = screen.getByTitle("Sanitized source document for Example judgment");
  expect(frame).toHaveAttribute("sandbox", "");
  expect(frame).toHaveAttribute("srcdoc", html);
  const body = new DOMParser().parseFromString(frame.getAttribute("srcdoc")!, "text/html");
  expect(body.querySelector("mark")).toBeNull();
  expect(body.querySelector("script")).toBeNull();
  expect(screen.queryByText(/Citation locations cannot be mapped/)).toBeNull();
  window.dispatchEvent(
    new MessageEvent("message", {
      source: (frame as HTMLIFrameElement).contentWindow,
      data: { type: "citation-add", start: 0, end: 5 },
    }),
  );
  expect(onAddCitation).not.toHaveBeenCalled();
  expect(onProvenancePick).not.toHaveBeenCalled();
  rerender(<WorkspaceSourcePane {...props} view="text" />);
  expect(container.querySelector(".source-text mark[data-active-anchor=true]")).not.toBeNull();
  expect(screen.queryByTitle("Sanitized source document for Example judgment")).toBeNull();
});
