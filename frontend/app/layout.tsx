import './globals.css'

export const viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#020617',
}

export const metadata = {
  title: 'WaterfallHunter — Paper Research Terminal',
  description: 'Observational USDT perpetual futures monitoring. Paper-only, no live orders.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  )
}
