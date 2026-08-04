/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Compact "research terminal" palette.
        ink: "#0b1220",
        panel: "#0f1729",
        edge: "#1e293b",
        muted: "#94a3b8",
        accent: "#38bdf8",
        long: "#34d399",
        short: "#f87171",
        watch: "#fbbf24",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
