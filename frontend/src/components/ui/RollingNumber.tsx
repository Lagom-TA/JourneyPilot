import React from 'react';
import { AnimatePresence, m } from 'motion/react';
import { cn } from '../../lib/utils';
import { duration, easing, transitions } from '../../lib/motion';


export interface RollingNumberProps {
  value: number;
  format: (value: number) => string;
  prefix?: string;
  className?: string;
  digitHeightEm?: number;
  testId?: string;
}

const DEFAULT_DIGIT_HEIGHT = 1.1;

const DigitColumn: React.FC<{ digit: number; heightEm: number }> = ({
  digit,
  heightEm,
}) => {
  const targetY = `-${digit * heightEm}em`;
  return (
    <span
      className="relative inline-block tabular-nums"
      style={{
        height: `${heightEm}em`,
        lineHeight: `${heightEm}em`,
        width: '1ch',
        // clip-path 不改变行内基线；overflow 裁切会让数字窗口按底边对齐。
        clipPath: 'inset(0)',
      }}
    >
      {/* 不可见的流内数字保留行盒，为窗口提供与数字格一致的基线。 */}
      <span aria-hidden className="invisible">0</span>
      <m.span
        // 隐藏整列数字的读屏输出，实际值只由根节点的 sr-only 文本提供。
        aria-hidden
        className="absolute left-0 top-0 flex flex-col"
        style={{ willChange: 'transform' }}
        animate={{ y: targetY }}
        transition={transitions.numberRoll()}
      >
        {Array.from({ length: 10 }, (_, n) => (
          <span
            key={n}
            // 数字格与基线占位使用相同排版，不能改为 flex 居中。
            className="block text-center tabular-nums"
            style={{ height: `${heightEm}em`, lineHeight: `${heightEm}em` }}
          >
            {n}
          </span>
        ))}
      </m.span>
    </span>
  );
};

/* 静态字符保持普通行内排版，避免偏离数字基线。 */
const StaticChar: React.FC<{ char: string }> = ({ char }) => <span>{char}</span>;

interface Cell {
  key: string;
  char: string;
  isDigit: boolean;
}

/* 按小数点或个位锚定 key，位数增长时保留已有数字列。 */
function buildCells(text: string): Cell[] {
  const chars = text.split('');
  const dotIdx = text.indexOf('.');
  let anchor = dotIdx >= 0 ? dotIdx - 1 : -1;
  if (anchor < 0) {
    for (let i = chars.length - 1; i >= 0; i--) {
      if (chars[i] >= '0' && chars[i] <= '9') {
        anchor = i;
        break;
      }
    }
  }
  if (anchor < 0) anchor = chars.length - 1;

  return chars.map((char, i) => {
    const isDigit = char >= '0' && char <= '9';
    const offset = i - anchor;
    return {
      key: isDigit ? `d${offset}` : `s${offset}:${char}`,
      char,
      isDigit,
    };
  });
}

export const RollingNumber: React.FC<RollingNumberProps> = ({
  value,
  format,
  prefix,
  className,
  digitHeightEm = DEFAULT_DIGIT_HEIGHT,
  testId,
}) => {
  const text = format(value);
  const cells = buildCells(text);

  return (
    <span
      data-testid={testId}
      data-value={prefix ? `${prefix}${text}` : text}
      className={cn('inline-flex items-baseline tabular-nums', className)}
    >
      <span className="sr-only">{prefix ? `${prefix}${text}` : text}</span>
      {prefix ? <StaticChar char={prefix} /> : null}
      <AnimatePresence initial={false}>
        {cells.map((cell) =>
          cell.isDigit ? (
            <m.span
              key={cell.key}
              className="inline-block"
              initial={{ opacity: 0, width: 0 }}
              animate={{ opacity: 1, width: '1ch' }}
              exit={{ opacity: 0, width: 0 }}
              transition={transitions.enter(duration.base)}
            >
              <DigitColumn digit={Number(cell.char)} heightEm={digitHeightEm} />
            </m.span>
          ) : (
            <m.span
              key={cell.key}
              className="inline-block"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: duration.fast, ease: easing.decelerate }}
            >
              <StaticChar char={cell.char} />
            </m.span>
          )
        )}
      </AnimatePresence>
    </span>
  );
};
