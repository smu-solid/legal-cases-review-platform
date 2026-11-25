import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FormEvent } from "react";
import { inviteReviewerToRoster } from "../../../api/admin";
import type { useDashboardFormState } from "./useAdminDashboard";

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function useReviewerInvitation({
  tenantId,
  inviteEmail,
  csrfToken,
  setInviteEmail,
  queryClient,
  setInviteEmailError,
}: {
  tenantId: string;
  inviteEmail: ReturnType<typeof useDashboardFormState>["inviteEmail"];
  csrfToken: string | null;
  setInviteEmail: ReturnType<typeof useDashboardFormState>["setInviteEmail"];
  queryClient: ReturnType<typeof useQueryClient>;
  setInviteEmailError: ReturnType<typeof useDashboardFormState>["setInviteEmailError"];
}) {
  const inviteMutation = useMutation({
    mutationFn: () => inviteReviewerToRoster(tenantId, { email: inviteEmail.trim() }, csrfToken),
    onSuccess: () => {
      setInviteEmail("");
      void queryClient.invalidateQueries({ queryKey: ["admin-reviewers", tenantId] });
    },
  });
  function handleInviteSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedEmail = inviteEmail.trim();
    if (!emailPattern.test(normalizedEmail)) {
      setInviteEmailError("Enter a valid reviewer email address.");
      return;
    }
    setInviteEmailError(null);
    inviteMutation.mutate();
  }
  return { inviteMutation, handleInviteSubmit };
}
