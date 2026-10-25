import { type PublicDeliveryBundle } from "../types/delivery";
export function canConfirmDeliveryBundle(current: PublicDeliveryBundle | null, candidate: PublicDeliveryBundle): boolean {
    if (!current || current.manifest.run_id !== candidate.manifest.run_id)
        return true;
    if (current.manifest.bundle_id === candidate.manifest.bundle_id)
        return true;
    const currentVector = [
        current.manifest.workspace_revision,
        current.manifest.fact_data_revision,
        current.manifest.weather_data_revision,
    ];
    const candidateVector = [
        candidate.manifest.workspace_revision,
        candidate.manifest.fact_data_revision,
        candidate.manifest.weather_data_revision,
    ];
    if (candidateVector.some((revision, index) => revision < currentVector[index])) {
        return false;
    }
    return candidateVector.some((revision, index) => revision > currentVector[index]);
}
