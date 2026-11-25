import { describe, expect, it } from "vitest";

import type { AdjudicationGroupedItem } from "../../api/types";
import { agreementStatus, matchesAgreementFilter } from "./adjudicationAgreement";

function itemWithAnswers(
  answers: Array<[valueCorrect: boolean, provenanceCorrect: boolean]>,
  requiredReviews = answers.length,
) {
  return {
    required_reviews: requiredReviews,
    submissions: answers.map(([valueCorrect, provenanceCorrect], index) => ({
      submission_id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      pseudonym: `Reviewer ${index + 1}`,
      value_correct: valueCorrect,
      provenance_correct: provenanceCorrect,
    })),
  } as AdjudicationGroupedItem;
}

describe("adjudication agreement classification", () => {
  it("classifies unanimous positive and negative answers across dynamic reviewer counts", () => {
    expect(agreementStatus(itemWithAnswers(Array(3).fill([true, true])))).toBe(
      "positive_agreement",
    );
    expect(agreementStatus(itemWithAnswers(Array(4).fill([false, false])))).toBe(
      "negative_agreement",
    );
  });

  it("classifies either unanimous mixed tuple as value/provenance disagreement", () => {
    expect(agreementStatus(itemWithAnswers(Array(3).fill([true, false])))).toBe(
      "value_provenance_disagreement",
    );
    expect(agreementStatus(itemWithAnswers(Array(4).fill([false, true])))).toBe(
      "value_provenance_disagreement",
    );
  });

  it("classifies any reviewer-to-reviewer difference as disagreement", () => {
    expect(
      agreementStatus(
        itemWithAnswers([
          [true, true],
          [true, false],
          [true, true],
        ]),
      ),
    ).toBe("disagreement");
  });

  it("does not classify incomplete legacy payloads but keeps them visible under All", () => {
    const incomplete = itemWithAnswers([[true, true]], 3);

    expect(agreementStatus(incomplete)).toBeNull();
    expect(matchesAgreementFilter(incomplete, "disagreement")).toBe(false);
    expect(matchesAgreementFilter(incomplete, "all")).toBe(true);
  });
});
