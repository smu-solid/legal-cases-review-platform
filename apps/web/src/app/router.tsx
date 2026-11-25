import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppLayout } from "../layout/AppLayout";
import { HomeRoute } from "../routes/HomeRoute";
import { ProtectedRoute } from "../routes/ProtectedRoute";
import { RequireCapability } from "../routes/RequireCapability";
import { RequireTenant } from "../routes/RequireTenant";
import { SetPasswordPage } from "../routes/account/SetPasswordPage";
import { SignInPage } from "../routes/account/SignInPage";
import { AdjudicationCampaignCasesPage } from "../routes/admin/AdjudicationCampaignCasesPage";
import { AdjudicationQueuePage } from "../routes/admin/AdjudicationQueuePage";
import { AdjudicationWorkspacePage } from "../routes/admin/AdjudicationWorkspacePage";
import { AdminDashboardPage } from "../routes/admin/AdminDashboardPage";
import { CampaignDetailPage } from "../routes/admin/CampaignDetailPage";
import { ReviewerCampaignQueuePage } from "../routes/reviewer/ReviewerCampaignQueuePage";
import { ReviewerQueuePage } from "../routes/reviewer/ReviewerQueuePage";
import { ReviewerWorkspacePage } from "../routes/reviewer/ReviewerWorkspacePage";
import { ForbiddenPage } from "../routes/system/ForbiddenPage";
import { NotFoundPage } from "../routes/system/NotFoundPage";
import { SessionExpiredPage } from "../routes/system/SessionExpiredPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <HomeRoute /> },
      {
        path: "sign-in",
        element: <SignInPage />,
      },
      { path: "accept-invite", element: <Navigate to="/sign-in" replace /> },
      { path: "activate", element: <SetPasswordPage activation /> },
      { path: "forgot-password", element: <Navigate to="/sign-in" replace /> },
      { path: "reset-password", element: <SetPasswordPage activation={false} /> },
      {
        path: "session-expired",
        element: <SessionExpiredPage />,
      },
      {
        path: "forbidden",
        element: <ForbiddenPage />,
      },
      {
        path: "t/:tenantId/review",
        element: (
          <ProtectedRoute>
            <RequireTenant>
              <RequireCapability anyOf={["can_review"]}>
                <ReviewerCampaignQueuePage />
              </RequireCapability>
            </RequireTenant>
          </ProtectedRoute>
        ),
      },
      {
        path: "t/:tenantId/review/campaigns/:campaignId",
        element: (
          <ProtectedRoute>
            <RequireTenant>
              <RequireCapability anyOf={["can_review"]}>
                <ReviewerQueuePage />
              </RequireCapability>
            </RequireTenant>
          </ProtectedRoute>
        ),
      },
      {
        path: "t/:tenantId/review/task/:assignmentId",
        element: (
          <ProtectedRoute>
            <RequireTenant>
              <RequireCapability anyOf={["can_review"]}>
                <ReviewerWorkspacePage />
              </RequireCapability>
            </RequireTenant>
          </ProtectedRoute>
        ),
      },
      {
        path: "t/:tenantId/admin",
        element: (
          <ProtectedRoute>
            <RequireTenant>
              <RequireCapability anyOf={["can_administer", "can_manage_campaigns", "can_allocate"]}>
                <AdminDashboardPage />
              </RequireCapability>
            </RequireTenant>
          </ProtectedRoute>
        ),
      },
      {
        path: "t/:tenantId/admin/campaigns/:campaignId",
        element: (
          <ProtectedRoute>
            <RequireTenant>
              <RequireCapability anyOf={["can_administer", "can_manage_campaigns", "can_allocate"]}>
                <CampaignDetailPage />
              </RequireCapability>
            </RequireTenant>
          </ProtectedRoute>
        ),
      },
      {
        path: "t/:tenantId/adjudication",
        element: (
          <ProtectedRoute>
            <RequireTenant>
              <RequireCapability anyOf={["can_adjudicate", "can_administer"]}>
                <AdjudicationQueuePage />
              </RequireCapability>
            </RequireTenant>
          </ProtectedRoute>
        ),
      },
      {
        path: "t/:tenantId/adjudication/campaigns/:campaignId",
        element: (
          <ProtectedRoute>
            <RequireTenant>
              <RequireCapability anyOf={["can_adjudicate", "can_administer"]}>
                <AdjudicationCampaignCasesPage />
              </RequireCapability>
            </RequireTenant>
          </ProtectedRoute>
        ),
      },
      {
        path: "t/:tenantId/adjudication/:adjudicationId",
        element: (
          <ProtectedRoute>
            <RequireTenant>
              <RequireCapability anyOf={["can_adjudicate", "can_administer"]}>
                <AdjudicationWorkspacePage />
              </RequireCapability>
            </RequireTenant>
          </ProtectedRoute>
        ),
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
