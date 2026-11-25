import { describe, expect, it } from "vitest";

import { parseJudgmentYearValue } from "./campaignCaseFilterYears";

describe("parseJudgmentYearValue", () => {
  it("accepts single, multiple, and inclusive year ranges", () => {
    expect(parseJudgmentYearValue("2010, 2014, 2016-2019")).toEqual({
      ranges: [
        { start: 2010, end: 2010 },
        { start: 2014, end: 2014 },
        { start: 2016, end: 2019 },
      ],
    });
  });

  it("sorts, deduplicates, and merges adjacent ranges", () => {
    expect(parseJudgmentYearValue("2018, 2016-2017, 2010, 2010")).toEqual({
      ranges: [
        { start: 2010, end: 2010 },
        { start: 2016, end: 2018 },
      ],
    });
  });

  it.each(["0999", "10000", "2019-2016", "2010, nope"])("rejects invalid input %s", (value) =>
    expect(() => parseJudgmentYearValue(value)).toThrow(),
  );
});
