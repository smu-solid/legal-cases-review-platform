# Import your own case

The app reads judgments, values to check, and passages that support those values from a SQLite file.
You prepare those inputs before importing. If your judgment is a PDF, convert the text you want to
show reviewers to HTML first. The demo generator is also available as a
[template for a larger conversion script](../src/review_platform/dataset/generate.py).

## 1. Prepare a judgment and one field to review

From the project folder, run `mkdir -p var`. Save this short example as `var/my-judgment.html`.

```html
<article data-review-document="true">
  <h1>River Trading v Hill Services</h1>
  <p>Judgment date: 12 February 2024.</p>
  <p>This fictional case concerns a delivery agreement.</p>
</article>
```

This example checks one value, the judgment date `2024-02-12`. The sentence beginning **Judgment
date** is the evidence a reviewer will see highlighted. You can adapt the same pattern to a case
title (`cases.title_raw`) or neutral citation (`cases.citation_neutral`).

## 2. Create the SQLite file

After [installing the local dependencies](../README.md#1-install-dependencies-and-create-your-settings-file),
run this from the project folder. It creates `var/my-cases.sqlite` and checks that the app can read
it. The example stops if the output file already exists.

```sh
uv run --locked python docs/examples/build_case_dataset.py
```

To use your own judgment, edit the file paths, case details, date and evidence sentence at the
top of the [example script](examples/build_case_dataset.py). Use a new case ID and output file.

The script finds the evidence sentence in the text the reviewer will see and saves its start and
end positions. If it appears more than once, use a longer passage that appears only once.

## 3. Load the case and find it in the app

1. Start PostgreSQL and run `make migrate` as described in
   [local setup](../README.md#2-start-the-database-and-load-the-fictional-cases).
2. In `.env`, set `REVIEW_DATASET_PATH=var/my-cases.sqlite`.
3. Run the following from the project folder. If you've initialized the demo before, use your
   existing demo password. The command loads the configured file and reports `Demo ready: 1 cases`
   for this file.

   ```sh
   REVIEW_DEMO_PASSWORD='replace-this-with-your-own-password' make demo
   ```

4. Start or restart the API with `make api-run`, then sign in as admin. In the campaign form,
   choose **Upload case IDs** and upload a UTF-8 text file with `MY-CASE-001` on its own line.
   Select **All fields** and create the campaign. The case has one field to review, **Judgment
   date**. [Complete your first review](user-guide.md) shows how to assign and review it.

Changing the file in `.env` changes which input the next import reads. The cases the app already
loaded stay in PostgreSQL, along with your reviews. Use a unique case ID for each new case.

## Format reference

- **Documents** are HTML. The document hash links the case and its evidence to the same document.
  The optional `<article data-review-document="true">` marks the part to show reviewers. The app
  strips active content and limits documents to 16 MiB before cleaning and 8 MiB after rendering.
- **Cases** include a collection key for dataset compatibility. The example uses `sample_a`.
  Each case repeats its ID, collection, and document hash inside `payload_json`. Use `YYYY-MM-DD`
  for the date column.
- **Fields** and **relations** follow the [input types](../src/review_platform/dataset/types.py).
  Use a [supported field name](../src/review_platform/review/grouping.py) for each field to review.
  A comparison candidate can be `null`. Add citations or statutes under `relations[]` only when
  you want them reviewed.
- **Evidence positions**, when supplied, use zero-based character positions in the normalized plain
  text. The end position is excluded, and the selected text must equal the snippet. The app finds
  the snippet in the displayed text and converts the positions for browser highlights at import.
  Both positions can be `null` if unavailable.
- **Local import** currently uses `make demo`. It creates the demo accounts if they are missing and
  runs in development or test mode. The **Upload case IDs** control selects cases already loaded
  into the app.
