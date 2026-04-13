/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#060816",
        panel: "#11172a",
        cyan: "#3cf6d0",
        blue: "#57a4ff",
        danger: "#ff577f",
        warn: "#ffb347",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(60, 246, 208, 0.18), 0 0 24px rgba(87, 164, 255, 0.18)",
      },
    },
  },
  plugins: [],
};
