import { getCurrentDeliveryBundle } from "../api/delivery";
import { apiErrorDetailString } from "../../../lib/apiErrorDetail";
import { isPublicDeliveryBundle, type PublicDeliveryBundle } from "../types/delivery";
export function conflictCurrentBundleId(error: unknown): string | null {
    return apiErrorDetailString(error, 'current_bundle_id');
}
export async function readCurrentBundleAfterConflict(runId: string, sessionId: string | null): Promise<PublicDeliveryBundle> {
    const bundle = await getCurrentDeliveryBundle(runId, sessionId);
    if (!isPublicDeliveryBundle(bundle) || bundle.manifest.run_id !== runId) {
        throw new Error('current Delivery Bundle read after a conflict does not belong to this run');
    }
    return bundle;
}
