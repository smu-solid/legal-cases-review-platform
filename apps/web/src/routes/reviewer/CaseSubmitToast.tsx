export function CaseSubmitToast({ message }: { message: string | null }) {
  if (!message) {
    return null;
  }
  return (
    <div className="notice notice-success" role="status">
      {message}
    </div>
  );
}
