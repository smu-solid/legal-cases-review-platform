import type { FieldGroup, GroupItem } from "../../api/types";
import { WorkspaceGroupSections } from "../../components/WorkspaceGroupSections";
import type { LocalAnswer } from "./reviewerAnswerState";
import { itemStatus } from "./reviewerAnswerState";
export function GroupList({
  groups,
  activeItemId,
  answers,
  onSelect,
  onAdd,
  activeAddGroupId,
  onAddFocus,
}: {
  groups: FieldGroup[];
  activeItemId: string | null;
  answers: Record<string, LocalAnswer>;
  onSelect: (item: GroupItem) => void;
  onAdd?: (group: FieldGroup) => void;
  activeAddGroupId?: string | null;
  onAddFocus?: (id: string) => void;
}) {
  return (
    <nav className="workspace-nav" aria-label="Grouped review fields">
      <WorkspaceGroupSections
        groups={groups}
        activeItemId={activeItemId}
        getItemId={(item) => item.review_unit_id}
        getItemLabel={(item) => item.item_label}
        getItemValue={(item) =>
          item.reviewer_proposal
            ? `Reviewer-added: ${answers[item.review_unit_id]?.corrected_value || item.extracted_value_display}`
            : item.extracted_value_display
        }
        getItemStatus={(item) => itemStatus(answers[item.review_unit_id])}
        isMissing={(item) => item.extraction_state === "missing"}
        onSelect={onSelect}
        activeGroupId={
          activeAddGroupId ??
          groups.find((g) =>
            g.items.some((i) => i.review_unit_id === activeItemId && i.reviewer_proposal),
          )?.group_id
        }
        renderGroupEnd={(group) => {
          const fullGroup = groups.find((g) => g.group_id === group.group_id)!;
          return fullGroup.add_item_label && onAdd ? (
            <button
              type="button"
              className="field-item add-item-row"
              data-add-group={group.group_id}
              onFocus={() => onAddFocus?.(group.group_id)}
              onKeyDown={(event) => {
                if (event.repeat && event.key === "Enter") event.preventDefault();
              }}
              onClick={() => onAdd(fullGroup)}
            >
              + Add {fullGroup.add_item_label}
            </button>
          ) : null;
        }}
      />
    </nav>
  );
}
