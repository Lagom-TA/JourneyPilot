import React from 'react';
import { cn } from '../../lib/utils';
import postmarkRing from '../../assets/marks/postmark.png';


// 遮罩按 2 倍分辨率存储，显示尺寸不超过 96px 以避免位图模糊。
const RING_PX = 96;

// 遮罩中心可排字的净空占全宽的 64.6%。
const CLEAR_RATIO = 0.646;

function stampDate(iso: string): { year: string; day: string; full: string } | null {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  const p = (n: number) => String(n).padStart(2, '0');
  const year = String(at.getFullYear());
  const day = `${p(at.getMonth() + 1)}.${p(at.getDate())}`;
  return { year, day, full: `${year}.${day}` };
}

export const Postmark: React.FC<{ generatedAt: string | null; className?: string }> = ({
  generatedAt,
  className,
}) => {
  const stamped = generatedAt ? stampDate(generatedAt) : null;
  if (!stamped) return null;

  return (
    <div
      data-postmark={stamped.full}
      className={cn('relative shrink-0', className)}
      style={{ width: RING_PX, height: RING_PX }}
    >
      <span
        aria-hidden
        style={{
          width: RING_PX,
          height: RING_PX,
          maskImage: `url(${postmarkRing})`,
          WebkitMaskImage: `url(${postmarkRing})`,
          maskSize: 'contain',
          WebkitMaskSize: 'contain',
          maskRepeat: 'no-repeat',
          WebkitMaskRepeat: 'no-repeat',
          maskPosition: 'center',
          WebkitMaskPosition: 'center',
        }}
        className="block bg-ink-secondary/25"
      />
      <span
        className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 text-center font-mono text-[11px] leading-none tabular-nums tracking-[0.04em] text-ink-secondary"
        style={{ padding: `0 ${Math.round((RING_PX * (1 - CLEAR_RATIO)) / 2)}px` }}
      >
        <span>{stamped.year}</span>
        <span>{stamped.day}</span>
      </span>
    </div>
  );
};
