import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MemberSourceValues } from "./MemberSourceValues";

describe("MemberSourceValues", () => {
  it("renders every recorded value and the disagreement badge without collection names", () => {
    render(
      <MemberSourceValues
        values={[
          { case: "CAS-000001", source_system: "sample_a", value: "2020-01-01" },
          { case: "CAS-000002", source_system: "sample_b", value: "2020-03-15" },
        ]}
        disagreement={true}
      />,
    );
    const block = screen.getByTestId("member-source-values");
    expect(block.textContent).not.toContain("sample_a");
    expect(block.textContent).toContain("2020-01-01");
    expect(block.textContent).not.toContain("sample_b");
    expect(block.textContent).toContain("2020-03-15");
    expect(block.textContent).toContain("values differ");
  });

  it("renders agreeing multi-source values without the disagreement badge", () => {
    render(
      <MemberSourceValues
        values={[
          { case: "CAS-000001", source_system: "sample_a", value: "Tan J" },
          { case: "CAS-000002", source_system: "sample_b", value: "Tan J" },
        ]}
        disagreement={false}
      />,
    );
    const block = screen.getByTestId("member-source-values");
    expect(block.textContent).toContain("Recorded values");
    expect(block.textContent).not.toContain("values differ");
  });

  it("renders nothing for a single-observation family", () => {
    render(
      <MemberSourceValues
        values={[{ case: "CAS-000001", source_system: "sample_a", value: "Tan J" }]}
        disagreement={false}
      />,
    );
    expect(screen.queryByTestId("member-source-values")).toBeNull();
  });

  it("lets the reviewer inspect each member's own evidence with its document attribution", () => {
    render(
      <MemberSourceValues
        values={[
          {
            case: "CAS-000001",
            source_system: "sample_a",
            value: "Tan J",
            evidence: [{ snippet: "Coram: Tan J", source_hash: "a".repeat(64), kind: "quote" }],
          },
          {
            case: "CAS-000002",
            source_system: "sample_b",
            value: "Tan J",
            evidence: [{ snippet: "Before: Tan J", source_hash: "b".repeat(64), kind: "quote" }],
          },
        ]}
        disagreement={false}
      />,
    );
    const blocks = screen.getAllByTestId("member-source-evidence");
    expect(blocks).toHaveLength(2);
    expect(blocks[0].textContent).toContain("Coram: Tan J");
    expect(blocks[0].textContent).toContain("aaaaaaaaaaaa");
    expect(blocks[1].textContent).toContain("Before: Tan J");
    expect(blocks[1].textContent).toContain("bbbbbbbbbbbb");
  });

  it("marks a truncated preview so the full value is sought on the subject record", () => {
    render(
      <MemberSourceValues
        values={[
          {
            case: "CAS-000001",
            source_system: "sample_a",
            value: "x".repeat(300),
            value_truncated: true,
          },
          { case: "CAS-000002", source_system: "sample_b", value: "y" },
        ]}
        disagreement={true}
      />,
    );
    expect(screen.getByTestId("member-source-values").textContent).toContain("(truncated preview)");
  });
});
