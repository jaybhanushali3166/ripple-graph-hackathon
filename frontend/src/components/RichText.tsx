import { Fragment, type ReactNode } from 'react';

// A deliberately small Markdown subset for model answers: paragraphs, "- " / "* " bullets,
// **bold** and `code` (shown as plain text). Never renders HTML from the model.
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <Fragment key={i}>{part.slice(1, -1)}</Fragment>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

export function RichText({ text, className }: { text: string; className?: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [], ordered = false;
  const flush = () => {
    if (!bullets.length) return;
    const items = bullets.map((b, i) => <li key={i}>{inline(b)}</li>);
    blocks.push(ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    bullets = [];
  };
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    const bullet = line.match(/^([-*•]|\d+\.)\s+(.*)$/);
    if (bullet) {
      const isOrdered = /\d/.test(bullet[1]);
      if (bullets.length && isOrdered !== ordered) flush();
      ordered = isOrdered; bullets.push(bullet[2]); continue;
    }
    flush();
    if (!line) continue;
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    blocks.push(<p key={blocks.length}>{inline(heading ? `**${heading[1]}**` : line)}</p>);
  }
  flush();
  return <div className={`rich-text${className ? ` ${className}` : ''}`}>{blocks}</div>;
}
