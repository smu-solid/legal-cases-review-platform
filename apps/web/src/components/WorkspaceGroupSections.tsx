import { useEffect, useRef, useState, type ReactNode } from "react";

export type WorkspaceItemStatusKind = "submitted" | "draft" | "in_progress" | "not_started";

export type WorkspaceItemStatus = {
  label: string;
  kind: WorkspaceItemStatusKind;
};

export type WorkspaceGroup<TItem> = {
  group_id: string;
  group_label: string;
  group_kind: "atomic" | "non_atomic";
  description?: string | null;
  items: TItem[];
  completed_count: number;
  item_count: number;
};

export function WorkspaceGroupSections<TItem>({
  groups,
  activeItemId,
  getItemId,
  getItemLabel,
  getItemValue,
  getItemStatus,
  isMissing,
  onSelect,
  activeGroupId,
  renderGroupEnd,
  getItemTag,
}: {
  groups: WorkspaceGroup<TItem>[];
  activeItemId: string | null;
  getItemId: (item: TItem) => string;
  getItemLabel: (item: TItem) => string;
  getItemValue: (item: TItem) => string;
  getItemStatus: (item: TItem) => WorkspaceItemStatus;
  isMissing: (item: TItem) => boolean;
  onSelect: (item: TItem) => void;
  activeGroupId?: string | null;
  renderGroupEnd?: (group: WorkspaceGroup<TItem>) => ReactNode;
  getItemTag?: (item: TItem) => string | undefined;
}) {
  const itemRefs = useRef(new Map<string, HTMLButtonElement>());
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => setExpanded({}), [groups]);
  useEffect(() => setExpanded({}), [activeItemId]);
  useEffect(() => {
    const focused = document.activeElement;
    if (!(focused instanceof HTMLElement) || !focused.classList.contains("field-item")) return;
    itemRefs.current.get(activeItemId ?? "")?.focus({ preventScroll: true });
  }, [activeItemId]);

  return groups.map((group) => {
    const repeatable = group.group_kind === "non_atomic" && group.items.length > 1;
    const activeInGroup =
      activeGroupId === group.group_id ||
      group.items.some((item) => getItemId(item) === activeItemId);
    const isOpen =
      activeGroupId === group.group_id || !repeatable
        ? true
        : group.group_id in expanded
          ? expanded[group.group_id]
          : activeInGroup;
    return (
      <section className="group-section" key={group.group_id}>
        <button
          type="button"
          className={repeatable ? "group-title-row group-toggle" : "group-title-row is-static"}
          aria-expanded={repeatable ? isOpen : undefined}
          onClick={() => {
            if (repeatable) {
              if (isOpen) {
                setExpanded((current) => ({ ...current, [group.group_id]: false }));
                return;
              }
              setExpanded((current) => ({ ...current, [group.group_id]: true }));
            }
            const first = group.items[0];
            if (first) onSelect(first);
          }}
        >
          <span className="group-title-line">
            <h3>
              {repeatable ? (
                <span aria-hidden="true" className="group-chevron">
                  {isOpen ? "▾" : "▸"}
                </span>
              ) : null}
              {group.group_label}
            </h3>
            <span className="group-count">
              {group.completed_count}/{group.item_count}
            </span>
          </span>
        </button>
        {group.description && isOpen ? <p>{group.description}</p> : null}
        {isOpen ? (
          <div className="item-stack">
            {group.items.map((item) => {
              const id = getItemId(item);
              const label = getItemLabel(item);
              const value = getItemValue(item);
              const status = getItemStatus(item);
              const memberCard = repeatable;
              const valueClass = isMissing(item)
                ? "field-item-value field-item-value-missing"
                : "field-item-value";
              return (
                <button
                  aria-label={`${label}: ${value} (${status.label})${getItemTag?.(item) ? ` — ${getItemTag(item)}` : ""}`}
                  className={activeItemId === id ? "field-item is-active" : "field-item"}
                  key={id}
                  data-review-item={id}
                  ref={(node) => {
                    if (node) itemRefs.current.set(id, node);
                    else itemRefs.current.delete(id);
                  }}
                  title={`${value} — ${status.label}`}
                  type="button"
                  onClick={(event) => {
                    event.currentTarget.focus({ preventScroll: true });
                    onSelect(item);
                  }}
                >
                  <span className="field-item-row">
                    <span aria-hidden="true" className={`status-dot status-dot-${status.kind}`} />
                    {memberCard ? (
                      <strong className={valueClass}>{value}</strong>
                    ) : (
                      <span className="field-item-label">{label}</span>
                    )}
                  </span>
                  {getItemTag?.(item) ? (
                    <span className="status-chip">{getItemTag(item)}</span>
                  ) : null}
                  {memberCard ? null : (
                    <strong className={`${valueClass} field-item-value-indented`}>{value}</strong>
                  )}
                </button>
              );
            })}
            {renderGroupEnd?.(group)}
          </div>
        ) : null}
      </section>
    );
  });
}
