import { AlertCircle } from 'lucide-react';
import type { ReactNode } from 'react';
export function InlineNotice({ children, tone = 'warning' }: { children: ReactNode; tone?: 'warning' | 'error' | 'info' }) {
  return <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : 'status'}><AlertCircle size={15} aria-hidden="true" /><div>{children}</div></div>;
}
