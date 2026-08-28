/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0d0d0d",
        panel: "#141414",
        card: "#161616",
        border: "#262626",
      },
    },
  },
  plugins: [],
}

