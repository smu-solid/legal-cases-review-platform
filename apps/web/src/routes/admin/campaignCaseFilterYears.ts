export interface JudgmentYearRange {
  start: number;
  end: number;
}

export function parseJudgmentYearValue(value: string): { ranges: JudgmentYearRange[] } {
  const ranges: JudgmentYearRange[] = [];
  for (const rawPart of value.split(",")) {
    const part = rawPart.trim();
    const match = /^(\d{4})(?:\s*[-–]\s*(\d{4}))?$/.exec(part);
    if (!match) {
      throw new Error("Use years such as 2010, 2014, or 2016-2019.");
    }
    const start = Number(match[1]);
    const end = Number(match[2] ?? match[1]);
    if (start < 1000 || end > 9999) {
      throw new Error("Judgment years must be from 1000 through 9999.");
    }
    if (start > end) {
      throw new Error("A judgment year range must start before it ends.");
    }
    ranges.push({ start, end });
  }
  if (!ranges.length) throw new Error("Enter at least one judgment year.");
  ranges.sort((left, right) => left.start - right.start || left.end - right.end);
  const merged: JudgmentYearRange[] = [];
  for (const range of ranges) {
    const previous = merged.at(-1);
    if (previous && range.start <= previous.end + 1) {
      previous.end = Math.max(previous.end, range.end);
    } else {
      merged.push({ ...range });
    }
  }
  return { ranges: merged };
}
