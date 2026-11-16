// Minos brand theme for Fluent UI: logo colours (navy, teal, green), League Spartan,
// softer rounded corners and navy-tinted shadows.

import { type BrandVariants, createDarkTheme, createLightTheme, type Theme } from '@fluentui/react-components'

export const brandColors = {
  navy: '#0B2D4E',
  teal: '#039BB0',
  green: '#01928C',
}

// Shades 10–80 run from near-black to the logo navy (primary buttons in light mode),
// 90–160 from navy through the logo teal to a pale tint (accents in dark mode).
const minos: BrandVariants = {
  10: '#020A12',
  20: '#041321',
  30: '#061B2E',
  40: '#07213A',
  50: '#082541',
  60: '#092947',
  70: '#0A2B4B',
  80: '#0B2D4E',
  90: '#0E4A68',
  100: '#10677F',
  110: '#0A8197',
  120: '#039BB0',
  130: '#2FB3C4',
  140: '#66C9D5',
  150: '#A1DEE6',
  160: '#D6F1F4',
}

const fontFamilyBase = "'League Spartan', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
const fontFamilyMonospace = "ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Consolas, monospace"

const shared: Partial<Theme> = {
  fontFamilyBase,
  fontFamilyMonospace,
  // League Spartan has a small x-height: nudge the text sizes up a step.
  fontSizeBase100: '11px',
  fontSizeBase200: '13px',
  fontSizeBase300: '15px',
  fontSizeBase400: '17px',
  fontSizeBase500: '21px',
  fontSizeBase600: '25px',
  lineHeightBase300: '22px',
  borderRadiusSmall: '4px',
  borderRadiusMedium: '8px',
  borderRadiusLarge: '12px',
  borderRadiusXLarge: '16px',
}

function shadows(rgb: string, strength: number): Partial<Theme> {
  const a = (x: number) => `rgba(${rgb}, ${(x * strength).toFixed(3)})`
  return {
    shadow2: `0 1px 2px ${a(0.06)}`,
    shadow4: `0 1px 2px ${a(0.05)}, 0 2px 8px ${a(0.06)}`,
    shadow8: `0 2px 4px ${a(0.05)}, 0 6px 16px ${a(0.08)}`,
    shadow16: `0 4px 8px ${a(0.06)}, 0 12px 28px ${a(0.1)}`,
    shadow28: `0 8px 16px ${a(0.08)}, 0 20px 44px ${a(0.14)}`,
    shadow64: `0 16px 32px ${a(0.1)}, 0 40px 80px ${a(0.18)}`,
  }
}

export const minosLight: Theme = {
  ...createLightTheme(minos),
  ...shared,
  ...shadows('11, 45, 78', 1),
  colorNeutralForeground1: '#0F2236',
  colorNeutralForeground2: '#33465B',
  colorNeutralForeground3: '#64758A',
  colorNeutralBackground1: '#FFFFFF',
  colorNeutralBackground2: '#F3F6F9',
  colorNeutralBackground3: '#EBF0F5',
  colorNeutralBackground1Hover: '#F5F8FB',
  colorSubtleBackgroundHover: '#EEF3F7',
  colorSubtleBackgroundPressed: '#E3EAF1',
  colorNeutralStroke1: '#D2DAE3',
  colorNeutralStroke2: '#E3E8EE',
  colorNeutralStroke3: '#EDF1F5',
  colorBrandBackgroundHover: '#13406A',
  colorBrandBackgroundPressed: '#07213A',
  colorBrandForegroundLink: '#037C8E',
  colorBrandForegroundLinkHover: '#0B2D4E',
  colorCompoundBrandBackground: brandColors.teal,
  colorCompoundBrandBackgroundHover: '#038A9D',
  colorCompoundBrandBackgroundPressed: '#027685',
  colorCompoundBrandStroke: brandColors.teal,
  colorCompoundBrandStrokeHover: '#038A9D',
  colorCompoundBrandForeground1: '#037C8E',
  colorStrokeFocus2: brandColors.teal,
}

const darkBase = createDarkTheme(minos)
export const minosDark: Theme = {
  ...darkBase,
  ...shared,
  ...shadows('0, 0, 0', 2.6),
  colorNeutralForeground1: '#E8EEF4',
  colorNeutralForeground2: '#BCC8D5',
  colorNeutralForeground3: '#8597AB',
  colorNeutralBackground1: '#111C28',
  colorNeutralBackground2: '#0A131C',
  colorNeutralBackground3: '#172433',
  colorNeutralBackground1Hover: '#172433',
  colorSubtleBackgroundHover: '#1A2838',
  colorSubtleBackgroundPressed: '#203043',
  colorNeutralStroke1: '#2F4054',
  colorNeutralStroke2: '#233244',
  colorNeutralStroke3: '#1C2939',
  colorBrandBackground: '#0A8197',
  colorBrandBackgroundHover: '#039BB0',
  colorBrandBackgroundPressed: '#10677F',
  colorBrandBackgroundSelected: '#10677F',
  colorBrandForeground1: '#2FB3C4',
  colorBrandForegroundLink: '#66C9D5',
  colorBrandForegroundLinkHover: '#A1DEE6',
  colorCompoundBrandBackground: '#2FB3C4',
  colorCompoundBrandStroke: '#2FB3C4',
  colorCompoundBrandForeground1: '#2FB3C4',
  colorStrokeFocus2: '#2FB3C4',
}
