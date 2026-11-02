import React from 'react';
import { CloudSun } from 'lucide-react';
import type { PublicWeatherAdjustment } from '../../types/weather';

interface WeatherSuggestionsProps {
  suggestions: readonly PublicWeatherAdjustment[];
  readOnly: boolean;
  onDiscuss: (suggestion: PublicWeatherAdjustment, event: React.MouseEvent<HTMLButtonElement>) => void;
}

export const WeatherSuggestions: React.FC<WeatherSuggestionsProps> = ({ suggestions, readOnly, onDiscuss }) => {
  if (suggestions.length === 0) return null;

  return (
    <section aria-label="天气建议" data-testid="weather-suggestions" className="mb-4 rounded-card border border-stroke bg-surface p-4">
      <h2 className="flex items-center gap-2 text-sm font-medium text-ink"><CloudSun size={16} />天气建议</h2>
      <ul className="mt-3 space-y-3">
        {suggestions.map((suggestion) => (
          <li key={suggestion.proposal_id} className="text-sm leading-5 text-ink-secondary">
            <p><time dateTime={suggestion.date}>{suggestion.date}</time> · {suggestion.severity === 'high' ? '天气影响较大' : '留意天气变化'}</p>
            <p className="mt-1 text-ink">{suggestion.summary}</p>
            {!readOnly && (
              <button
                type="button"
                data-conversation-trigger={`weather-${suggestion.proposal_id}`}
                className="mt-2 text-sm font-medium text-accent hover:underline"
                onClick={(event) => onDiscuss(suggestion, event)}
              >讨论调整</button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
};
