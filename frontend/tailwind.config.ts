import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    // 替换而非扩展默认表，防止表外圆角回落到 Tailwind 默认值。
    borderRadius: {
      none: '0',
      label: 'var(--radius-label)',
      card: 'var(--radius-card)',
      panel: 'var(--radius-panel)',
      full: 'var(--radius-full)',
    },

    // 替换默认动效表，使未显式指定的过渡也使用公共 token。
    transitionDuration: {
      DEFAULT: 'var(--dur-base)',
      fast: 'var(--dur-fast)',
      base: 'var(--dur-base)',
      slow: 'var(--dur-slow)',
      emphasis: 'var(--dur-emphasis)',
      'number-roll': 'var(--dur-number-roll)',
      loop: 'var(--dur-loop)',
    },
    transitionTimingFunction: {
      DEFAULT: 'var(--ease-standard)',
      standard: 'var(--ease-standard)',
      decelerate: 'var(--ease-decelerate)',
      accelerate: 'var(--ease-accelerate)',
    },

    // 替换默认阴影表，避免表外档位继续使用内置阴影。
    boxShadow: {
      none: 'none',
      sm: 'var(--shadow-sm)',
      md: 'var(--shadow-md)',
      lg: 'var(--shadow-lg)',
    },

    extend: {
      colors: {
        // RGB 三元组允许 Tailwind 为颜色组合透明度。
        bg: 'rgb(var(--color-bg-rgb) / <alpha-value>)',
        panel: 'rgb(var(--color-panel-rgb) / <alpha-value>)',
        surface: 'rgb(var(--color-surface-rgb) / <alpha-value>)',
        'surface-soft': 'rgb(var(--color-surface-soft-rgb) / <alpha-value>)',
        highlight: 'rgb(var(--color-highlight-rgb) / <alpha-value>)',
        stroke: 'rgb(var(--color-stroke-rgb) / <alpha-value>)',
        ink: {
          DEFAULT: 'rgb(var(--color-ink-rgb) / <alpha-value>)',
          secondary: 'rgb(var(--color-ink-secondary-rgb) / <alpha-value>)',
          muted: 'rgb(var(--color-ink-muted-rgb) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'rgb(var(--color-accent-rgb) / <alpha-value>)',
          hover: 'rgb(var(--color-accent-hover-rgb) / <alpha-value>)',
          soft: 'rgb(var(--color-accent-soft-rgb) / <alpha-value>)',
        },
        'on-accent': 'rgb(var(--color-on-accent-rgb) / <alpha-value>)',
        success: 'rgb(var(--color-success-rgb) / <alpha-value>)',
        error: 'rgb(var(--color-error-rgb) / <alpha-value>)',
        warning: 'rgb(var(--color-warning-rgb) / <alpha-value>)',
        chart: 'rgb(var(--color-chart-rgb) / <alpha-value>)',
        vermilion: 'rgb(var(--color-vermilion-rgb) / <alpha-value>)',
        navy: 'rgb(var(--color-navy-rgb) / <alpha-value>)',
      },
      opacity: {
        8: '0.08',
        12: '0.12',
        18: '0.18',
      },
      // 拉丁字体排在前面，汉字与全角标点交给后面的中文字体。
      fontFamily: {
        sans: ['"Inter Variable"', '"Noto Sans SC Variable"', 'system-ui', 'sans-serif'],
        mono: ['"SF Mono"', 'Monaco', 'Consolas', '"Courier New"', 'monospace'],
        display: ['"Noto Serif SC Subset"', '"Noto Serif SC Variable"', 'serif'],
      },
      animation: {
        'fade-in': 'fadeIn var(--dur-slow) var(--ease-decelerate)',
        'slide-up': 'slideUp var(--dur-slow) var(--ease-decelerate)',
        'slide-in-right': 'slideInRight var(--dur-slow) var(--ease-decelerate)',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        slideInRight: {
          from: { opacity: '0', transform: 'translateX(20px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config
