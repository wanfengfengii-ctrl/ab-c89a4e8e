// Thin API client. Request sequencing (stale-response guard) is owned by the
// caller: every call accepts an AbortSignal, and App compares request ids
// before applying a response so that a late answer can never overwrite a
// newer draft.

export class ApiError extends Error {
  constructor(status, detail) {
    super(`HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, payload, signal) {
  let res;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(0, [
      { loc: [], msg: `无法连接分析服务：${err.message}`, type: "network" },
    ]);
  }

  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }

  if (!res.ok) {
    const detail =
      body && Array.isArray(body.detail)
        ? body.detail
        : [{ loc: [], msg: body?.detail || `请求失败（HTTP ${res.status}）` }];
    throw new ApiError(res.status, detail);
  }
  return body;
}

export const solveMessages = (messages, signal) =>
  request("/api/solve", { messages }, signal);

export const analyzeOrder = (messages, order, signal) =>
  request("/api/analyze", { messages, order }, signal);
