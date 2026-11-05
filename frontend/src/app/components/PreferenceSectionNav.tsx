import { useApp } from '../state/AppContext';
import { type ActiveView } from '../state/state';
import { getViewHref } from '../../lib/viewHref';

export const PREFERENCE_LINKS: Array<{ view: ActiveView; label: string }> = [
  { view: 'user-preferences', label: '我的偏好' },
  { view: 'presets', label: '旅行风格' },
  { view: 'knowledge-base', label: '资料来源' },
];

export function PreferenceSectionNav() {
  const { state, dispatch } = useApp();
  return <nav className="archive-section-nav" aria-label="偏好与资料分类">
    {PREFERENCE_LINKS.map(({ view, label }) => <a key={view} href={getViewHref(view)} aria-current={state.activeView === view ? 'page' : undefined} onClick={(event) => {
      event.preventDefault();
      dispatch({ type: 'SET_ACTIVE_VIEW', payload: view });
    }}>{label}</a>)}
  </nav>;
}
