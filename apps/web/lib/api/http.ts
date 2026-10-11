/** Shared transport only; service URLs, authentication and domain types stay local. */
export async function serviceRequest(
  baseUrl: string,
  path: string,
  options?: RequestInit,
  allowedStatuses: readonly number[] = [],
): Promise<Response> {
  const headers = new Headers(options?.headers);
  const isFormData =
    typeof FormData !== "undefined" && options?.body instanceof FormData;
  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${baseUrl}${path}`, { ...options, headers });
  if (!response.ok && !allowedStatuses.includes(response.status)) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return response;
}

export async function serviceJson<T>(
  baseUrl: string,
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await serviceRequest(baseUrl, path, options);
  return response.json() as Promise<T>;
}
