function resolveContentOffset(root: Node, container: Node, offset: number): number {
  const range = document.createRange();
  range.selectNodeContents(root);
  range.setEnd(container, offset);
  return range.toString().length;
}

// Resolve the selected rendered text, rather than searching raw HTML or a first occurrence. Range
// serialization stays aligned with source_render.content across text nodes and mark wrappers.
export function resolveProvenancePick(
  root: Node,
  range: Range,
): { text: string; charStart: number; charEnd: number } | null {
  const rawText = range.toString();
  const text = rawText.trim();
  if (text.length < 2) return null;

  const start = resolveContentOffset(root, range.startContainer, range.startOffset);
  const end = resolveContentOffset(root, range.endContainer, range.endOffset);
  const leadingTrim = rawText.length - rawText.trimStart().length;
  const trailingTrim = rawText.length - rawText.trimEnd().length;
  const charStart = Math.min(start, end) + leadingTrim;
  const charEnd = Math.max(start, end) - trailingTrim;
  if (charEnd <= charStart) return null;
  return { text, charStart, charEnd };
}
