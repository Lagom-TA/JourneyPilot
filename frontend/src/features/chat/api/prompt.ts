import { fetchJson, LLM_TIMEOUT_MS } from "../../../lib/http";
export async function optimizePrompt(text: string) {
    return fetchJson<{
        success: boolean;
        optimized_prompt?: string;
        error_message?: string;
    }>('/optimize-prompt', {
        method: 'POST',
        body: JSON.stringify({ prompt: text }),
    }, LLM_TIMEOUT_MS);
}
