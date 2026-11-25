import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { listCampaignCases } from "../../../api/admin";
import type { useCampaignControls } from "./useCampaignDetail";

export function useCampaignCases({
  setCasePages,
  setCaseCursor,
  setCaseHasMore,
  campaignId,
  tenantId,
  caseCursor,
}: {
  setCasePages: ReturnType<typeof useCampaignControls>["setCasePages"];
  setCaseCursor: ReturnType<typeof useCampaignControls>["setCaseCursor"];
  setCaseHasMore: ReturnType<typeof useCampaignControls>["setCaseHasMore"];
  campaignId: string;
  tenantId: string;
  caseCursor: ReturnType<typeof useCampaignControls>["caseCursor"];
}) {
  useEffect(() => {
    setCasePages([]);
    setCaseCursor(null);
    setCaseHasMore(false);
  }, [campaignId, setCaseCursor, setCaseHasMore, setCasePages]);

  const casesQuery = useQuery({
    queryKey: ["campaign-cases", tenantId, campaignId, caseCursor],
    queryFn: () => listCampaignCases(tenantId, campaignId, { limit: 25, cursor: caseCursor }),
    enabled: Boolean(tenantId && campaignId),
  });

  useEffect(() => {
    if (!casesQuery.data) {
      return;
    }
    setCasePages((current) =>
      caseCursor === null ? casesQuery.data.items : [...current, ...casesQuery.data.items],
    );
    setCaseHasMore(casesQuery.data.has_more);
    // caseCursor intentionally excluded: this effect reacts to new page data, not cursor changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [casesQuery.data]);
  return { casesQuery };
}
