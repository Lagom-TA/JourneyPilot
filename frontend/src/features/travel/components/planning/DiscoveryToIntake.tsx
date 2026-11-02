import { ArrowRight } from 'lucide-react';
import { useApp } from '../../../../app/state/AppContext';
import { useSendMessage } from '../../../../app/session/useSendMessage';
import { type PlaceIdentity } from '../../types/planner';
import { Button } from '../../../../components/ui/Button';
import { PlaceField } from './PlaceField';
import React from 'react';

export const DiscoveryToIntake: React.FC<{ rawInput: string }> = ({ rawInput }) => {
  const { state } = useApp();
  const { sendMessage } = useSendMessage();
  const [place, setPlace] = React.useState<PlaceIdentity | null>(null);
  return (
    <section className="rounded-card border border-stroke bg-panel p-5 shadow-sm" aria-labelledby="discovery-to-trip-title">
      <h2 id="discovery-to-trip-title" className="text-base font-semibold text-ink">选好目的地，继续完善这趟旅行</h2>
      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <PlaceField role="destination" value={place} onChange={setPlace} label="目的地" />
        <Button type="button" disabled={!place || state.isStreaming} onClick={() => {
          if (!place) return;
          const choice = `选择${place.name}，继续规划`;
          void sendMessage([rawInput, choice].filter(Boolean).join('\n'), { route: 'trip_planning', displayText: choice, assistantPendingLabel: '正在整理这趟旅行的信息' });
        }}>继续规划 <ArrowRight size={14} /></Button>
      </div>
    </section>
  );
};
