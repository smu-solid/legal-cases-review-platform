import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SafeSourceFrame } from "../../components/SafeSourceFrame";

describe("SafeSourceFrame", () => {
  it("renders sanitized HTML inside a fully locked-down sandbox iframe", () => {
    const html = "<h1>Judgment</h1><p>Body text</p>";
    render(<SafeSourceFrame html={html} title="Sanitized source document" />);

    const frame = screen.getByTitle("Sanitized source document") as HTMLIFrameElement;
    expect(frame.tagName).toBe("IFRAME");
    // Empty sandbox = deny all: no script execution, no same-origin access to the reviewer app.
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame).not.toHaveAttribute("sandbox", "allow-scripts");
    // The HTML lives in srcdoc, never injected into the reviewer DOM.
    expect(frame.getAttribute("srcdoc")).toContain("Judgment");
  });

  it("keeps untrusted markup out of the parent document (no dangerouslySetInnerHTML)", () => {
    const hostile = '<img src=x onerror="window.__xss=1" /><script>window.__xss=1</script>';
    render(<SafeSourceFrame html={hostile} title="Hostile source" />);

    // The markup is confined to the iframe srcdoc; it never becomes live nodes in the parent DOM,
    // and the empty sandbox prevents any script/handler from executing.
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect((window as unknown as { __xss?: number }).__xss).toBeUndefined();
    const frame = screen.getByTitle("Hostile source");
    expect(frame.getAttribute("sandbox")).toBe("");
  });

  it("loads a verified same-origin artifact URL without relaxing the sandbox", () => {
    render(
      <SafeSourceFrame
        src="/api/v1/tenants/t/review/adjudications/a/source-render/body"
        title="Adjudication source"
      />,
    );

    const frame = screen.getByTitle("Adjudication source");
    expect(frame).toHaveAttribute(
      "src",
      "/api/v1/tenants/t/review/adjudications/a/source-render/body",
    );
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame).not.toHaveAttribute("srcdoc");
  });
});
