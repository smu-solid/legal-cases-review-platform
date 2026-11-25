type ExtractedValueProps = {
  value: string;
  missing?: boolean;
};

export function ExtractedValue({ value, missing = false }: ExtractedValueProps) {
  return (
    <div className="extracted-value">
      <span>Extracted value</span>
      <strong className={missing ? "extracted-value-missing" : undefined}>{value}</strong>
    </div>
  );
}
