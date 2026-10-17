import { ArrowRight } from 'lucide-react';
import type { HistoryResponse } from '../api/types';
import { dateTime, fullDate } from '../lib/dates';
import { decisionLabel } from '../lib/decisions';
import { SourceChips, type OpenSource } from './SourceButton';
export function ForecastHistory({ histories, labels, onSource }: { histories: Record<string, HistoryResponse>; labels: Record<string, string>; onSource: OpenSource }) {
  return <section className="forecast-history"><h3>Forecast &amp; decision history</h3>
    {Object.entries(histories).map(([id, history]) => <details key={id} className="history-group" open={history.forecasts.length > 1}>
      <summary>{labels[id] || id}<span className="small muted">{history.forecasts.length} accepted {history.forecasts.length === 1 ? 'record' : 'records'}</span></summary>
      {history.forecasts.map(forecast => <div className="history-entry" key={forecast.id}>
        <div className="history-date"><span>{fullDate(forecast.available_at)}</span><ArrowRight size={13} aria-hidden="true" /><span className={`decision-tag${/^DEC-/.test(forecast.decision_id) ? ' decision-tag-code' : ''}`}>{decisionLabel(forecast.decision_id)}</span>{forecast.supersedes_id && <span className="small muted">supersedes {decisionLabel(forecast.supersedes_id)}</span>}</div>
        <p className="small muted">Effective {dateTime(forecast.valid_from)}{forecast.valid_to !== null ? ` until ${dateTime(forecast.valid_to)}` : ' · current accepted record'}</p>
        <SourceChips citations={forecast.citations} onOpen={onSource} />
      </div>)}
    </details>)}
    <p className="small muted history-note">Recorded paths only. Forecasts are not automatically replanned.</p>
  </section>;
}
