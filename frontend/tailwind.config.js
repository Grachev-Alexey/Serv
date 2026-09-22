/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Базовые поверхности (тёмная тема профессионального VMS)
        bg: "#0a0e16",
        surface: "#111725",
        elevated: "#161e2e",
        hairline: "#222c3e",
        // Бренд-акцент
        brand: {
          DEFAULT: "#3b82f6",
          hover: "#5b9bff",
          soft: "rgba(59,130,246,0.12)",
        },
        // Текст
        ink: {
          DEFAULT: "#e8eef8",
          muted: "#8b98ad",
          faint: "#59677e",
        },
        // Статусы
        ok: "#34d399",
        warn: "#fbbf24",
        danger: "#f87171",
        live: "#ff4d4f",
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.125rem",
      },
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -12px rgba(0,0,0,0.6)",
        lift: "0 8px 30px -8px rgba(0,0,0,0.7)",
        glow: "0 0 0 1px rgba(59,130,246,0.4), 0 8px 30px -8px rgba(59,130,246,0.35)",
      },
      keyframes: {
        "pulse-ring": {
          "0%": { boxShadow: "0 0 0 0 rgba(52,211,153,0.55)" },
          "70%": { boxShadow: "0 0 0 6px rgba(52,211,153,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(52,211,153,0)" },
        },
        "live-blink": {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "pulse-ring": "pulse-ring 2s infinite",
        "live-blink": "live-blink 1.6s ease-in-out infinite",
        "fade-in": "fade-in 0.3s ease-out",
      },
    },
  },
  plugins: [],
};
