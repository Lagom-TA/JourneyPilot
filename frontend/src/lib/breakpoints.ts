import screenWidths from '../../breakpoints.json';

export const VIEWPORT_QUERIES = {
  compact: `(width < ${screenWidths.sm}px)`,
  mobile: `(width < ${screenWidths.lg}px)`,
} as const;
