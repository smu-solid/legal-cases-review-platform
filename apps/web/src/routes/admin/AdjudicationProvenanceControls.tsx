import type { DecisionPaneProps } from "./AdjudicationDecisionPane";

export function AdjudicationProvenanceControls(props: DecisionPaneProps) {
  return (
    <>
      {props.editable && props.verdict === "all_wrong" ? (
        <div className="provenance-correction-action">
          <button
            type="button"
            className={props.pickingProvenance ? "primary-button is-active" : "primary-button"}
            disabled={
              !props.activeItem?.proposal_item && !props.activeItem?.evidence_window_ids.length
            }
            onClick={props.onToggleProvenancePicking}
          >
            {props.pickingProvenance
              ? "Cancel marking (Esc)"
              : "Mark corrected provenance in source"}
          </button>
          <p className="provenance-pick-guidance">
            {props.activeItem?.proposal_item
              ? "Select the source text that supports the correction. Marked supporting provenance is required for a corrected value."
              : "Optionally select the source text that supports the corrected decision."}
          </p>
        </div>
      ) : null}
      {props.correctedProvenanceSpans.length ? (
        <div className="evidence-box">
          <span>Marked corrected provenance</span>
          {props.correctedProvenanceSpans.map((span, index) => {
            const snippet = (
              span.selected_text ?? props.sourceContent.slice(span.char_start, span.char_end)
            ).trim();
            return (
              <div className="provenance-marked-item" key={`${span.char_start}-${span.char_end}`}>
                {snippet ? (
                  <p className="provenance-marked-text" title={snippet}>
                    “{snippet.length > 120 ? `${snippet.slice(0, 120)}…` : snippet}”
                  </p>
                ) : null}
                <p className="provenance-marked-row">
                  <span className="provenance-marked-range">
                    chars {span.char_start}–{span.char_end}
                  </span>
                  {props.editable ? (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => props.onClearProvenance(index)}
                    >
                      clear
                    </button>
                  ) : null}
                </p>
              </div>
            );
          })}
        </div>
      ) : null}
    </>
  );
}
