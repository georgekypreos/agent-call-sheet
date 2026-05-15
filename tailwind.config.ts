import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Pale sky blue palette from the Python dashboard
        bg: "#eff6ff",
        card: "#ffffff",
        border: {
          DEFAULT: "#94a3b8",
          strong: "#475569",
        },
        text: "#0f172a",
        muted: "#475569",
        hint: "#64748b",
        accent: {
          DEFAULT: "#4f46e5",
          hover: "#4338ca",
          bg: "#eef2ff",
          soft: "#e0e7ff",
        },
        success: { DEFAULT: "#047857", bg: "#ecfdf5" },
        danger: { DEFAULT: "#be123c", bg: "#fff1f2" },
        warn: { DEFAULT: "#b45309", bg: "#fffbeb" },
        info: { DEFAULT: "#0369a1", bg: "#f0f9ff" },
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "system-ui", "sans-serif"],
      },
      boxShadow: {
        "card-sm": "0 1px 2px rgba(15, 23, 42, 0.04)",
        "card-md": "0 1px 3px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15, 23, 42, 0.04)",
        "card-lg": "0 4px 12px rgba(15, 23, 42, 0.06), 0 2px 4px rgba(15, 23, 42, 0.04)",
      },
    },
  },
  plugins: [],
};

export default config;
