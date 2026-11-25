import { describe, expect, it } from "vitest";

import { resolveProvenancePick } from "../../components/provenancePick";

// Builds a `<pre>` whose text content is `content`, mirroring what `renderMarkedSource` produces
// for a render with no active marks (a single text node child) -- the simplest faithful stand-in
// for the reviewer's source-text pane.
function buildSourcePane(content: string): HTMLPreElement {
  const pre = document.createElement("pre");
  pre.textContent = content;
  document.body.appendChild(pre);
  return pre;
}

// Selects `[start, end)` of `root`'s single text-node content and returns the Range, mirroring
// what `window.getSelection().getRangeAt(0)` would give the reviewer after a mouse drag.
function selectRange(root: HTMLElement, start: number, end: number): Range {
  const textNode = root.firstChild;
  if (!textNode) {
    throw new Error("root has no text node");
  }
  const range = document.createRange();
  range.setStart(textNode, start);
  range.setEnd(textNode, end);
  return range;
}

describe("resolveProvenancePick", () => {
  it("disambiguates a repeated phrase by selection position, not first occurrence", () => {
    const phrase = "the appeal is dismissed";
    const content =
      `Introduction. ${phrase} in the court below, for the reasons given. ` +
      `Held: on appeal, ${phrase} for the reasons that follow.`;

    const firstStart = content.indexOf(phrase);
    const secondStart = content.lastIndexOf(phrase);
    expect(secondStart).toBeGreaterThan(firstStart); // sanity: the phrase really repeats

    const root = buildSourcePane(content);
    const range = selectRange(root, secondStart, secondStart + phrase.length);

    const picked = resolveProvenancePick(root, range);

    expect(picked).not.toBeNull();
    expect(picked?.text).toBe(phrase);
    // The stored span must address the second occurrence's own offsets -- a first-occurrence
    // text search (the prior `content.indexOf(text)` bug) would have wrongly returned
    // `firstStart` here even though the reviewer selected the second occurrence.
    expect(picked?.charStart).toBe(secondStart);
    expect(picked?.charEnd).toBe(secondStart + phrase.length);
    expect(content.slice(picked!.charStart, picked!.charEnd)).toBe(phrase);
  });

  it("trims incidental leading/trailing whitespace from the drag into the stored span", () => {
    const content = "Paragraph one. Second body paragraph BODYTWO referring to a source.";
    const phrase = "Second body paragraph BODYTWO";
    // Simulate a drag that overshot by a trailing space before "referring".
    const dragStart = content.indexOf(phrase);
    const dragEnd = dragStart + phrase.length + 1;

    const root = buildSourcePane(content);
    const range = selectRange(root, dragStart, dragEnd);

    const picked = resolveProvenancePick(root, range);

    expect(picked?.text).toBe(phrase);
    expect(picked?.charStart).toBe(dragStart);
    expect(picked?.charEnd).toBe(dragStart + phrase.length);
  });

  it("returns null for a selection under two characters", () => {
    const content = "Short.";
    const root = buildSourcePane(content);
    const range = selectRange(root, 0, 1);

    expect(resolveProvenancePick(root, range)).toBeNull();
  });
});
