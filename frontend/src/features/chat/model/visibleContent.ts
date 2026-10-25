const DESTINATION_JSON_BLOCK = /<!--\s*DESTINATION_JSON\b[\s\S]*?-->/gi;
const DESTINATION_JSON_OPEN = /<!--\s*DESTINATION_JSON\b/i;
export function stripAssistantControlBlocks(content: string): string {
    const withoutCompleteBlocks = content.replace(DESTINATION_JSON_BLOCK, '');
    const unterminatedStart = withoutCompleteBlocks.search(DESTINATION_JSON_OPEN);
    const visible = unterminatedStart >= 0
        ? withoutCompleteBlocks.slice(0, unterminatedStart)
        : withoutCompleteBlocks;
    return visible.trimEnd();
}
