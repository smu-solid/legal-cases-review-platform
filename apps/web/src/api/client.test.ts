import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiDownload, apiRequest } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
});

// A fresh Response per call: a Response body can only be read once.
function mockFetch(body: string, status: number, contentType: string) {
  vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(new Response(body, { status, headers: { "content-type": contentType } })),
  );
}

describe("apiRequest error body parsing", () => {
  it("parses an application/problem+json error body so code and detail are readable", async () => {
    // Error responses are RFC7807 problem+json, not plain application/json. The client must still
    // parse them or every code/detail lookup silently falls back to a generic message.
    const problem = {
      title: "Campaign contains reviewer work",
      status: 422,
      code: "campaign_delete_work_exists",
      detail: "This campaign has saved, submitted, or revision-requested reviewer work.",
    };
    mockFetch(JSON.stringify(problem), 422, "application/problem+json");

    let caught: unknown;
    try {
      await apiRequest("/x");
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(422);
    expect((caught as ApiError).body).toMatchObject({
      code: "campaign_delete_work_exists",
      detail: expect.stringContaining("reviewer work"),
    });
  });

  it("still parses a plain application/json success body", async () => {
    mockFetch(JSON.stringify({ ok: true }), 200, "application/json");
    await expect(apiRequest<{ ok: boolean }>("/x")).resolves.toEqual({ ok: true });
  });

  it("still parses a plain application/json error body (unchanged behavior)", async () => {
    mockFetch(
      JSON.stringify({ code: "not_found", detail: "The resource was not found." }),
      404,
      "application/json",
    );

    await expect(apiRequest("/whatever")).rejects.toSatisfy((error: unknown) => {
      const apiError = error as ApiError;
      expect((apiError.body as { code?: string }).code).toBe("not_found");
      return true;
    });
  });
});

describe("apiDownload", () => {
  it("returns the text attachment and server-provided safe filename", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("CAS-1\nCAS-2\n", {
        status: 200,
        headers: {
          "content-type": "text/plain",
          "content-disposition":
            'attachment; filename="sample_b_criminal_2010_2014_2016to2019.txt"',
        },
      }),
    );

    const download = await apiDownload("/export", { filter: true });

    expect(download.filename).toBe("sample_b_criminal_2010_2014_2016to2019.txt");
    expect(download.blob.type).toBe("text/plain");
    expect(download.blob.size).toBeGreaterThan(0);
  });
});
