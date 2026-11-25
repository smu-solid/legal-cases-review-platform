import { useQuery } from "@tanstack/react-query";
import {
  getGroupedReviewBundle,
  getSourceRenderAnchors,
  getSourceRenderBody,
  getSourceRenderMetadata,
  listReviewerCampaignQueue,
  listReviewerCaseQueue,
} from "../../api/reviewer";

export function useReviewerWorkspaceQueries(
  tenantId: string,
  assignmentId: string,
  campaignIdParam: string | null,
) {
  const bundleQuery = useQuery({
    queryKey: ["reviewer-grouped-bundle", tenantId, assignmentId],
    queryFn: () => getGroupedReviewBundle(tenantId, assignmentId),
    enabled: Boolean(tenantId && assignmentId),
  });

  const campaignsQuery = useQuery({
    queryKey: ["reviewer-campaign-queue", tenantId],
    queryFn: () => listReviewerCampaignQueue(tenantId),
    enabled: Boolean(tenantId && campaignIdParam),
    retry: false,
  });
  const campaignSummary = campaignsQuery.data?.campaigns?.find(
    (campaign) => campaign.campaign_id === campaignIdParam,
  );

  // Ordered case list for within-campaign Previous/Next footer navigation. Deliberately a DISTINCT
  // query key from the campaign case-list page's *infinite* query (`["reviewer-case-queue", ...]`):
  // sharing it collides two incompatible cache shapes (a flat `{items}` page vs `{pages}`), which
  // intermittently left `.items` undefined here and disabled Next even when more cases existed. A
  // Navigation is limited to the first 100 cases; the campaign list supports pagination.
  const caseQueueQuery = useQuery({
    queryKey: ["reviewer-case-queue-nav", tenantId, campaignIdParam],
    queryFn: () => listReviewerCaseQueue(tenantId, campaignIdParam ?? "", { limit: 100 }),
    enabled: Boolean(tenantId && campaignIdParam),
    retry: false,
  });

  // Fetch the sanitized-HTML artifact metadata; when it exists and is `sanitized_html`, the body is
  // fetched and rendered in a sandboxed iframe. A 404 (no artifact emitted) leaves the query in
  // error and the pane falls back to the grouped bundle's inline `safe_text` render.
  const sourceMetaQuery = useQuery({
    queryKey: ["source-render-meta", tenantId, assignmentId],
    queryFn: () => getSourceRenderMetadata(tenantId, assignmentId),
    enabled: Boolean(tenantId && assignmentId),
    retry: false,
  });

  const apiMeta = sourceMetaQuery.data;
  const hasHtmlArtifact =
    apiMeta?.render_mode === "sanitized_html" && apiMeta.artifact_mime_type === "text/html";

  const sourceBodyQuery = useQuery({
    queryKey: ["source-render-body", tenantId, assignmentId],
    queryFn: () => getSourceRenderBody(tenantId, assignmentId),
    enabled: Boolean(tenantId && assignmentId) && hasHtmlArtifact,
    retry: false,
  });

  const sourceAnchorsQuery = useQuery({
    queryKey: ["source-render-anchors", tenantId, assignmentId],
    queryFn: () => getSourceRenderAnchors(tenantId, assignmentId),
    enabled: Boolean(tenantId && assignmentId) && hasHtmlArtifact,
    retry: false,
  });

  const documentHtml = hasHtmlArtifact ? (sourceBodyQuery.data ?? null) : null;
  const htmlLoading = hasHtmlArtifact && sourceBodyQuery.isLoading;
  const artifactAnchorUnavailable = hasHtmlArtifact && sourceAnchorsQuery.isError;

  return {
    bundleQuery,
    campaignSummary,
    caseQueueQuery,
    documentHtml,
    htmlLoading,
    artifactAnchorUnavailable,
  };
}
