import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef } from "react";
import { makeIdempotencyKey } from "../../api/client";
import {
  changeProposalMembership,
  getProposalWorkspace,
  writeProposalDecision,
  type MembershipChange,
} from "../../api/proposalAdjudication";
import type { AdjudicationCaseWorkspace, AdjudicationWorkspaceItem } from "../../api/types";
import type { LocalAdjudicationDecision } from "./adjudicationDecisionState";
import { mergeProposalWorkspace, proposalDecisionBody } from "./adjudicationProposals";

export function useProposalAdjudication(
  tenant: string,
  anchor: string,
  base: AdjudicationCaseWorkspace | undefined,
  csrf: string | null | undefined,
) {
  const client = useQueryClient();
  const keys = useRef(new Map<string, string>());
  const query = useQuery({
    queryKey: ["proposal-adjudication", tenant, anchor],
    queryFn: () => getProposalWorkspace(tenant, anchor),
    enabled: Boolean(base),
    retry: false,
  });
  const keyFor = useCallback((body: unknown) => {
    const signature = JSON.stringify(body);
    let key = keys.current.get(signature);
    if (!key) {
      key = makeIdempotencyKey("proposal-adjudication");
      keys.current.set(signature, key);
    }
    return key;
  }, []);
  const write = useCallback(
    async (item: AdjudicationWorkspaceItem, local: LocalAdjudicationDecision, submit: boolean) => {
      const target = {
        ...item.proposal_item!,
        lock_version: local.proposalVersion ?? item.proposal_item!.lock_version,
      };
      const body = proposalDecisionBody(item, local);
      const result = await writeProposalDecision(
        tenant,
        anchor,
        target,
        body,
        submit,
        csrf,
        keyFor([tenant, anchor, target.id, target.lock_version, body, submit]),
      );
      client.setQueryData(["proposal-adjudication", tenant, anchor], result);
      return result;
    },
    [tenant, anchor, csrf, client, keyFor],
  );
  const change = useCallback(
    async (body: MembershipChange) => {
      const result = await changeProposalMembership(
        tenant,
        anchor,
        body,
        csrf,
        keyFor([tenant, anchor, body]),
      );
      client.setQueryData(["proposal-adjudication", tenant, anchor], result);
      await client.invalidateQueries({ queryKey: ["adjudication-case-workspace", tenant, anchor] });
      await client.invalidateQueries({ queryKey: ["adjudication-campaign-cases", tenant] });
      await client.invalidateQueries({ queryKey: ["adjudication-campaigns", tenant] });
      return result;
    },
    [tenant, anchor, csrf, client, keyFor],
  );
  const bundle = useMemo(() => mergeProposalWorkspace(base, query.data), [base, query.data]);
  return { bundle, query, write, change };
}
