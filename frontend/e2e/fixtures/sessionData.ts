export function sessionSummary(id: string) {
  return { session_id: id, title: `离线会话 ${id}`, status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-10-25T08:00:00Z', updated_at: '2026-10-25T08:00:00Z' };
}
export function sessionDetail(id: string) {
  return { ...sessionSummary(id), messages: [{ id: `${id}-history`, role: 'assistant', content: `${id} 的历史回答`, display_content: `${id} 的历史回答`, timestamp: '2026-10-25T08:00:00Z' }], next_before: null, has_more: false };
}
export { xianDeliveryBundle as deliveryBundle } from './xianBundle';
