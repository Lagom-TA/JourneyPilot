import React from 'react';
const STROKE = 1.75;
const GLYPHS: Record<string, {
    label: string;
    draw: React.ReactNode;
}> = {
    compass: {
        label: '罗盘',
        draw: (<>
        <circle cx="12" cy="12" r="7"/>
        <circle cx="12" cy="12" r="3"/>
        <path d="M12 1.5V4M12 20V22.5M1.5 12H4M20 12H22.5"/>
      </>),
    },
    landmark: {
        label: '地标',
        draw: (<>
        <path d="M3 7h18"/>
        <path d="M7 9.5V19M12 9.5V19M17 9.5V19"/>
      </>),
    },
    utensils: {
        label: '餐具',
        draw: (<>
        <circle cx="12" cy="12.5" r="4.75"/>
        <path d="M3.5 4.5V20.5M20.5 4.5V20.5"/>
      </>),
    },
    baby: {
        label: '亲子',
        draw: (<>
        <path d="M2 19.5h20"/>
        <circle cx="8" cy="15" r="4.5"/>
        <circle cx="17" cy="16.75" r="2.75"/>
      </>),
    },
    'piggy-bank': {
        label: '储蓄',
        draw: (<>
        <circle cx="12" cy="12" r="8"/>
        <path d="M4.25 14h15.5"/>
      </>),
    },
    crown: {
        label: '皇冠',
        draw: (<>
        <path d="M12 3L21 12L12 21L3 12Z"/>
        <path d="M7.5 7.5h9v9h-9Z"/>
      </>),
    },
    mountain: {
        label: '山峰',
        draw: (<>
        <path d="M2 20L9 6L16 20Z"/>
        <path d="M13.5 20L18 11.5L22.5 20Z"/>
      </>),
    },
    camera: {
        label: '相机',
        draw: (<>
        <path d="M3.5 3.5h17v17h-17Z"/>
        <circle cx="12" cy="12" r="4.5"/>
      </>),
    },
    heart: {
        label: '爱心',
        draw: (<>
        <circle cx="8.5" cy="12" r="6"/>
        <circle cx="15.5" cy="12" r="6"/>
      </>),
    },
    palette: {
        label: '艺术',
        draw: (<>
        <path d="M3 5h5v14h-5Z"/>
        <path d="M9.5 5h5v14h-5Z"/>
        <path d="M16 5h5v14h-5Z"/>
      </>),
    },
    music: {
        label: '音乐',
        draw: (<>
        <circle cx="8.75" cy="17.25" r="3.25"/>
        <path d="M12 17.25V5h6"/>
      </>),
    },
    map: {
        label: '地图',
        draw: (<>
        <path d="M3 5h18v14H3Z"/>
        <path d="M12 5v14M3 12h18"/>
      </>),
    },
    star: {
        label: '星标',
        draw: (<>
        <path d="M12 3L19.79 16.5H4.21Z"/>
        <path d="M12 21L4.21 7.5H19.79Z"/>
      </>),
    },
};
export const PRESET_ICON_CHOICES: ReadonlyArray<{
    value: string;
    label: string;
}> = Object.entries(GLYPHS).map(([value, { label }]) => ({ value, label }));
export function getPresetIcon(name: string, size: number): React.ReactNode {
    const glyph = GLYPHS[name];
    if (!glyph)
        return null;
    return (<svg data-style-glyph={name} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={STROKE} strokeLinecap="butt" strokeLinejoin="miter" aria-hidden focusable="false">
      {glyph.draw}
    </svg>);
}
