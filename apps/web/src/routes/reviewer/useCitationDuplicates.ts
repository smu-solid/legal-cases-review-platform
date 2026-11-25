import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../../api/client";
import type { components } from "../../api/generated/openapi";
import type { GroupItem } from "../../api/types";
import type { LocalAnswer } from "./reviewerAnswerState";
import { proposalInput, type ProposalInput } from "./reviewerProposals";

export type DuplicateCheck = components["schemas"]["CitationDuplicateCheck"];

export function useCitationDuplicates(
  tenantId: string,
  item: GroupItem | null,
  answer: LocalAnswer | undefined,
  csrfToken: string | null,
) {
  const [result, setResult] = useState<{
    signature: string;
    data?: DuplicateCheck;
    error?: string;
  }>();
  const request = useRef(0);
  const enabled = Boolean(item?.reviewer_proposal && answer && !answer.submitted);
  const assignmentId = item?.assignment_id ?? "";
  const proposalId = item?.review_unit_id ?? "";
  const body = enabled && item && answer ? JSON.stringify(proposalInput(item, answer)) : "";
  const signature = body ? JSON.stringify([tenantId, assignmentId, proposalId, body]) : "";

  const requestCheck = useCallback(
    async (assignmentId: string, proposalId: string, body: ProposalInput) => {
      const sequence = ++request.current;
      const signature = JSON.stringify([tenantId, assignmentId, proposalId, JSON.stringify(body)]);
      try {
        const data = await apiRequest<DuplicateCheck>(
          `/tenants/${tenantId}/review/assignments/${assignmentId}/proposals/${proposalId}/duplicate-check`,
          { method: "POST", body, csrfToken },
        );
        if (sequence === request.current) setResult({ signature, data });
      } catch {
        if (sequence === request.current)
          setResult({
            signature,
            error: "Duplicate check unavailable. Edit, save or submit again to retry.",
          });
      }
    },
    [tenantId, csrfToken],
  );

  useEffect(() => {
    if (!body) return;
    const input: ProposalInput = JSON.parse(body);
    const timer = window.setTimeout(() => {
      if (input.value.trim() || input.provenance?.length)
        void requestCheck(assignmentId, proposalId, input);
    }, 300);
    return () => {
      window.clearTimeout(timer);
      request.current += 1;
    };
  }, [assignmentId, proposalId, body, requestCheck]);

  const check = useCallback(
    (target: GroupItem, value: LocalAnswer) =>
      requestCheck(target.assignment_id, target.review_unit_id, proposalInput(target, value)),
    [requestCheck],
  );

  return {
    enabled,
    data: result?.signature === signature ? result.data : undefined,
    error: result?.signature === signature ? result.error : undefined,
    check,
  };
}
export type CitationFeedback = ReturnType<typeof useCitationDuplicates>;
