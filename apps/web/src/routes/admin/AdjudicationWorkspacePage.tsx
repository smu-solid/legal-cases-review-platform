import { ReviewerLeaveGuard } from "../reviewer/ReviewerLeaveGuard";
import { AdjudicationDraftRecovery } from "./AdjudicationDraftRecovery";
import { AdjudicationWorkspaceContent } from "./AdjudicationWorkspaceContent";
import { AdjudicationWorkspaceLoadState } from "./AdjudicationWorkspaceLoadState";
import { ProposalMembershipControls } from "./ProposalMembershipControls";
import { useAdjudicationWorkspace } from "./adjudicationWorkspace/useAdjudicationWorkspace";

export function AdjudicationWorkspacePage() {
  const { loadState, workspace } = useAdjudicationWorkspace();
  if (loadState) return <AdjudicationWorkspaceLoadState {...loadState} />;
  if (!workspace) return null;
  const { content, leaveGuard, recovery, proposalError, onMembershipChange } = workspace;
  return (
    <>
      <ReviewerLeaveGuard {...leaveGuard} />
      <AdjudicationDraftRecovery {...recovery} />
      {proposalError ? (
        <p role="alert">Reviewer-added items could not be loaded. Refresh to retry.</p>
      ) : null}
      <AdjudicationWorkspaceContent
        {...content}
        proposalControls={
          content.activeItem?.proposal_item ? (
            <ProposalMembershipControls
              key={content.activeItem.proposal_item.id}
              item={content.activeItem}
              bundle={content.bundle}
              onChange={onMembershipChange}
            />
          ) : undefined
        }
      />
    </>
  );
}
