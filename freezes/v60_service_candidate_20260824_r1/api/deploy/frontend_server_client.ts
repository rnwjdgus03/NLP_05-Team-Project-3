// Server-side only. Never expose KOSIS_SERVICE_API_KEY in browser JavaScript.

export type KosisClaim = {
  claim_id?: string;
  article_id?: string;
  title: string;
  date: string;
  url?: string;
  claim_text: string;
  prev_sentence?: string;
  next_sentence?: string;
  article_context?: string;
};

export type KosisJob = {
  job_id: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  progress_step?: string;
  result_url?: string;
  error?: string | null;
};

const baseUrl = process.env.KOSIS_API_BASE_URL ?? "http://127.0.0.1:8000";
const apiKey = process.env.KOSIS_SERVICE_API_KEY;

async function apiFetch(path: string, init?: RequestInit) {
  if (!apiKey) throw new Error("KOSIS_SERVICE_API_KEY is not configured");
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`KOSIS API ${response.status}: ${await response.text()}`);
  return response.json();
}

export async function submitKosisClaims(claims: KosisClaim[]): Promise<KosisJob> {
  return apiFetch("/v1/verifications", {
    method: "POST",
    body: JSON.stringify({ input_stage: "claims", claims }),
  });
}

export async function getKosisJob(jobId: string): Promise<KosisJob> {
  return apiFetch(`/v1/verifications/${jobId}`);
}

export async function getKosisResult(jobId: string) {
  return apiFetch(`/v1/verifications/${jobId}/result`);
}
