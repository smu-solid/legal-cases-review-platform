import { useEffect, useMemo, useRef, useState } from "react";
import { makeIdempotencyKey } from "../../api/client";
import type { FieldGroup, GroupItem, ReviewerGroupingBundle } from "../../api/types";
import type { LocalAnswer } from "./reviewerAnswerState";
import {
  newProposal,
  persistProposal,
  projectProposals,
  proposalInput,
  type ReviewerProposal,
} from "./reviewerProposals";

export function useReviewerAdditions(
  source: ReviewerGroupingBundle | undefined,
  tenantId: string,
  assignmentId: string,
  csrfToken: string | null,
) {
  const [local, setLocal] = useState<Record<string, ReviewerProposal>>({});
  const keys = useRef(new Map<string, string>());
  useEffect(() => {
    setLocal({});
    keys.current.clear();
  }, [assignmentId, tenantId]);
  const bundle = useMemo(() => {
    if (!source) return undefined;
    const proposals = new Map((source.reviewer_additions ?? []).map((p) => [p.id, p]));
    Object.values(local).forEach((p) => {
      if (!proposals.has(p.id) || proposals.get(p.id)!.lock_version <= p.lock_version)
        proposals.set(p.id, p);
    });
    return projectProposals(source, [...proposals.values()], assignmentId);
  }, [source, local, assignmentId]);

  function start(group: FieldGroup) {
    const proposal = newProposal(group);
    setLocal((current) => ({ ...current, [proposal.id]: proposal }));
    return proposal;
  }

  async function persist(
    item: GroupItem,
    answer: LocalAnswer,
    version: number,
    state: "draft" | "submitted" | "removed",
  ) {
    const signature = JSON.stringify([
      item.review_unit_id,
      version,
      state,
      proposalInput(item, answer),
    ]);
    const key = keys.current.get(signature) ?? makeIdempotencyKey("proposal");
    keys.current.set(signature, key);
    const result = await persistProposal(tenantId, item, answer, version, state, csrfToken, key);
    setLocal((current) => ({ ...current, [result.id]: result }));
    return result;
  }

  return { bundle, start, persist };
}
