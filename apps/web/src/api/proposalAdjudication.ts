import { apiRequest } from "./client";
import type { components } from "./generated/openapi";

export type ProposalWorkspace = components["schemas"]["ProposalAdjudicationWorkspace"];
export type ProposalItem = components["schemas"]["ProposalDecisionItem"];
export type ProposalDecision = components["schemas"]["ProposalDecision"];
export type MembershipChange = components["schemas"]["ProposalMembershipChange"];
export type ProposalSpan = components["schemas"]["ProposalSpan"];
const path = (tenant: string, anchor: string) =>
  `/tenants/${tenant}/review/adjudications/${anchor}/proposal-items`;
export const getProposalWorkspace = (tenant: string, anchor: string) =>
  apiRequest<ProposalWorkspace>(path(tenant, anchor));
export const changeProposalMembership = (
  tenant: string,
  anchor: string,
  body: MembershipChange,
  csrfToken: string | null | undefined,
  idempotencyKey: string,
) =>
  apiRequest<ProposalWorkspace>(`${path(tenant, anchor)}/membership`, {
    method: "POST",
    body,
    csrfToken,
    idempotencyKey,
  });
export const writeProposalDecision = (
  tenant: string,
  anchor: string,
  item: ProposalItem,
  decision: ProposalDecision,
  submit: boolean,
  csrfToken: string | null | undefined,
  idempotencyKey: string,
) =>
  apiRequest<ProposalWorkspace>(`${path(tenant, anchor)}/${item.id}`, {
    method: "PUT",
    body: { expected_version: item.lock_version, decision, submit },
    csrfToken,
    idempotencyKey,
  });
