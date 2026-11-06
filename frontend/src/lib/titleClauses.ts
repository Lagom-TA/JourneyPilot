// 行程标题常写成「主题：副题」。按冒号拆成分句，让每个分句作为整体换行，
// 避免副题被从词中间拆开；分句本身放不下时仍会在句内换行。
export function splitTitleClauses(title: string): string[] {
  return title.match(/[^：:]+[：:]?|[：:]/g) ?? [title];
}
