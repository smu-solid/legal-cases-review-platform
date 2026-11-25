import type { AdjudicationCaseWorkspace, AdjudicationWorkspaceItem } from "../../api/types";
import { WorkspaceGroupSections } from "../../components/WorkspaceGroupSections";
import { agreementFilterOptions, type AgreementStatus } from "./adjudicationAgreement";

export function AdjudicationFieldNav({
  groups,
  activeItem,
  filter,
  onFilterChange,
  onSelect,
}: {
  groups: AdjudicationCaseWorkspace["field_groups"];
  activeItem: AdjudicationWorkspaceItem | null;
  filter: AgreementStatus;
  onFilterChange: (filter: AgreementStatus) => void;
  onSelect: (itemId: string) => void;
}) {
  return (
    <nav className="workspace-nav adjudication-field-nav" aria-label="Adjudication fields">
      <div className="adjudication-field-filter">
        <label htmlFor="agreement-status-filter">Agreement status</label>
        <select
          id="agreement-status-filter"
          value={filter}
          onChange={(event) => onFilterChange(event.target.value as AgreementStatus)}
        >
          {agreementFilterOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <div className="adjudication-field-groups">
        <WorkspaceGroupSections
          groups={groups.map((group) => ({
            ...group,
            completed_count: group.items.filter((item) => item.participation_status === "submitted")
              .length,
            item_count: group.items.length,
          }))}
          activeItemId={activeItem?.item_id ?? null}
          getItemId={(item) => item.item_id}
          getItemLabel={(item) => item.item_label}
          getItemValue={(item) =>
            item.proposal_item?.proposals.map((p) => p.value).join(" / ") ??
            item.extracted_value_display
          }
          getItemStatus={(item) =>
            item.participation_status === "submitted"
              ? { label: "Finished", kind: "submitted" }
              : item.draft || item.proposal_item?.draft
                ? { label: "Draft saved", kind: "draft" }
                : { label: "To adjudicate", kind: "not_started" }
          }
          isMissing={(item) => item.extracted_value_display === "No value extracted"}
          onSelect={(item) => onSelect(item.item_id)}
        />
        {!groups.length ? (
          <p className="adjudication-filter-empty" role="status">
            No fields match this filter.
          </p>
        ) : null}
      </div>
    </nav>
  );
}
