/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        panel: 'var(--panel)',
        'text-primary': 'var(--text-primary)',
        'text-muted': 'var(--text-muted)',
        'blue-electric': 'var(--blue-electric)',
        'blue-bright': 'var(--blue-bright)',
        'accent-orange': 'var(--accent-orange)',
        'cyan-highlight': 'var(--cyan-highlight)',
        'success-green': 'var(--success-green)',
        border: 'var(--border)',
      },
    },
  },
  plugins: [],
}

