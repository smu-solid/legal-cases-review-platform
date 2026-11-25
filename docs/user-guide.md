# Complete your first review

This walkthrough takes you through one fictional case using the accounts created during
[local setup](../README.md#run-the-demo-on-your-computer). Use the same demo password for each
account. Open the account menu in the top right and choose **Sign out** whenever you switch roles.

## 1. Create and publish a campaign

1. Sign in as `admin@example.test`. Under **Admin → Your campaigns**, use the **Create campaign draft** form.
2. Enter a campaign name such as `First review`. Keep the suggested campaign key and the default of
   two reviews per case. Under **Fields**, choose **Selected fields** and tick **Case metadata**.
3. Set **Case count** to **Exact number**, enter `1` under **Requested cases**, and click
   **Create campaign draft**.
4. In the campaign, tick **Reviewer One** and **Reviewer Two** under **Selected reviewers**. Click
   **Preview assignment plan**, check that each reviewer receives the case, then click
   **Publish assignments**.

## 2. Review the case twice

1. Sign in as `reviewer1@example.test`. Click **Open campaign queue** for `First review`, then
   **Open case**.
2. For each field, compare the extracted value with the highlighted passage. The app calls the
   passage used as evidence its **provenance**. **Text** shows the evidence highlights and lets you
   select supporting text. **Document** shows the formatted judgment for reading. Answer the
   questions about the value and its evidence.
3. If a value is wrong, choose **No**, fill in the reason and corrected value, and select supporting
   text if needed. Some demo titles are intentionally wrong. Try **Save draft** on one field and
   reload the page to see the saved answer.
4. Once you have answered every field, click **Review & submit case**, check the preview, then click
   **Confirm & submit case**. Sign in as `reviewer2@example.test` and do the same review independently.

## 3. Record the decisions

1. After both reviews have been submitted, sign in as `adjudicator@example.test`. Open
   **Adjudication → View cases** for `First review`, then click **Open** on the case.
2. Compare the two reviews with the judgment. Choose a decision for each field. For example, choose
   **All equivalent / supported** if both reviewers gave equally well-supported answers.
3. Click **Review & submit case**, then **Confirm & submit case**. Sign in as `admin@example.test`
   and complete the same adjudication steps. The demo asks both the adjudicator and the administrator
   for a decision. Once both have submitted, check the campaign in **Admin** to see its progress.

## Invite another reviewer

In **Admin**, use **Add reviewer**. In the default local setup, the app saves invitations and
password reset messages under `var/email_outbox/` as `.eml` files. Open the message and follow its
link to choose a password. The reviewer becomes eligible for assignments after activating the account.

When you create another campaign, you can use filters or upload a list of case IDs to select
from cases already loaded into the app. The saved filter or list applies every time you add cases.
You can change it in **Edit campaign**. Cases already in the campaign stay there.

**Export case IDs** downloads one list, using the applied filters when present. See
[Import your own case](dataset.md) to add a new judgment.
