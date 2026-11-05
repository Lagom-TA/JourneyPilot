import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { useApp } from '../../../app/state/AppContext';
import { listPresets } from '../api/presets';
import { describeRequestFailure, type RequestFailure } from '../../../lib/requestFailureMessage';

export function ActivePresetContext() {
  const { state, dispatch } = useApp();
  const { activePresetId, activePresetName } = state;
  const [notice, setNotice] = useState('');
  const [error, setError] = useState<RequestFailure | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!activePresetId) return;
    let disposed = false;
    void listPresets().then(presets => {
      if (disposed) return;
      setError(null);
      const active = presets.find(preset => preset.id === activePresetId);
      if (!active) {
        dispatch({ type: 'SET_ACTIVE_PRESET', payload: null });
        setNotice('之前选择的旅行风格已不可用，请重新选择。');
      } else if (active.name !== activePresetName) {
        dispatch({ type: 'SET_ACTIVE_PRESET', payload: { id: active.id, name: active.name } });
      }
    }).catch(err => { if (!disposed) setError(describeRequestFailure(err, '读取', '所选旅行风格')); });
    return () => { disposed = true; };
  }, [activePresetId, activePresetName, dispatch, retry]);
  if (!activePresetId && !notice) return null;
  return <div className="active-preset-context" role="status">
    {activePresetId ? <><span data-testid="preset-active-chip">{activePresetName}</span><button type="button" aria-label="取消旅行风格" onClick={() => dispatch({ type: 'SET_ACTIVE_PRESET', payload: null })}><X size={13} /></button></> : <><span>{notice}</span><button type="button" onClick={() => dispatch({ type: 'SET_ACTIVE_VIEW', payload: 'presets' })}>选择风格</button></>}
    {activePresetId && error && <span>{error.message}<button type="button" onClick={() => setRetry(value => value + 1)}>重试</button></span>}
  </div>;
}
