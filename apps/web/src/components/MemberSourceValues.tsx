type MemberEvidence = {
  snippet?: string;
  source_hash?: string;
  kind?: string;
};

type MemberSourceValue = {
  case: string;
  source_system: string;
  value: string;
  value_truncated?: boolean;
  evidence?: MemberEvidence[];
};

type MemberSourceValuesProps = {
  values: MemberSourceValue[];
  disagreement: boolean;
};

export function MemberSourceValues({ values, disagreement }: MemberSourceValuesProps) {
  if (values.length <= 1 && !disagreement) {
    return null;
  }
  return (
    <div
      className={`member-source-values${disagreement ? " member-source-values-disagreement" : ""}`}
      data-testid="member-source-values"
    >
      <span>
        Recorded values
        {disagreement ? (
          <strong className="member-source-disagreement-badge"> — values differ</strong>
        ) : null}
      </span>
      <ul>
        {values.map((member) => (
          <li key={`${member.case}:${member.source_system}`}>
            <span className="member-source-value">
              {member.value}
              {member.value_truncated ? (
                <em title="Preview truncated; full value available on the subject record">
                  {" "}
                  (truncated preview)
                </em>
              ) : null}
            </span>
            {member.evidence && member.evidence.length > 0 ? (
              <details className="member-source-evidence" data-testid="member-source-evidence">
                <summary>Evidence ({member.evidence.length})</summary>
                <ul>
                  {member.evidence.map((item, index) => (
                    <li key={`${member.case}:${index}`}>
                      <q>{item.snippet}</q>
                      {item.source_hash ? (
                        <span className="member-source-evidence-doc">
                          {" "}
                          [{item.source_hash.slice(0, 12)}]
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
