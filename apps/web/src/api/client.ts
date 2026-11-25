export const API_BASE_URL = import.meta.env.VITE_REVIEW_API_BASE_URL ?? "/api/v1";

export interface ApiClientConfig {
  baseUrl: string;
}

export const apiClientConfig: ApiClientConfig = {
  baseUrl: API_BASE_URL,
};

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(message);
  }
}

interface JsonRequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  idempotencyKey?: string;
  ifMatch?: number | string | null;
  csrfToken?: string | null;
}

export interface ApiDownload {
  blob: Blob;
  filename: string;
}

export async function apiRequest<T>(path: string, options: JsonRequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");

  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  if (options.idempotencyKey) {
    headers.set("Idempotency-Key", options.idempotencyKey);
  }

  if (options.ifMatch !== undefined && options.ifMatch !== null) {
    const version = String(options.ifMatch).replace(/^"|"$/g, "");
    headers.set("If-Match", `"${version}"`);
  }

  if (options.csrfToken) {
    headers.set("X-CSRF-Token", options.csrfToken);
  }

  const response = await fetch(`${apiClientConfig.baseUrl}${path}`, {
    ...options,
    headers,
    credentials: "include",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  const contentType = response.headers.get("content-type") ?? "";
  // Success responses use ``application/json``; error responses use RFC7807
  // ``application/problem+json``. Match any JSON media type (``+json`` structured suffix) so error
  // bodies are parsed too -- otherwise ``ApiError.body`` stays a raw string and every ``code``/
  // ``detail`` lookup falls through to a generic message.
  const isJson = /(^|\/|\+)json\b/.test(contentType);
  const responseText = await response.text();
  const body = responseText && isJson ? JSON.parse(responseText) : responseText;

  if (!response.ok) {
    throw new ApiError("Request failed", response.status, body);
  }

  return body as T;
}

export async function apiDownload(
  path: string,
  body: unknown,
  csrfToken?: string | null,
): Promise<ApiDownload> {
  const headers = new Headers({ Accept: "text/plain", "Content-Type": "application/json" });
  if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(`${apiClientConfig.baseUrl}${path}`, {
    method: "POST",
    headers,
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    let errorBody: unknown = text;
    try {
      errorBody = text ? JSON.parse(text) : text;
    } catch {
      // A non-JSON error body is still useful to the caller.
    }
    throw new ApiError("Request failed", response.status, errorBody);
  }
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "case_ids.txt";
  return { blob: await response.blob(), filename };
}

export function makeIdempotencyKey(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}
