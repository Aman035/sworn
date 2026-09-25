import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Sworn — execution integrity for Uniswap v4',
  description:
    'Measured hook divergence across mainnet, and a router that makes quote spoofing structurally impossible.',
};

const NAV = [
  ['/', 'Overview'],
  ['/hooks', 'Hook explorer'],
  ['/detection', 'Detection'],
  ['/attribution', 'Attribution'],
] as const;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="top">
          <div className="wrap">
            <div className="brand">
              <h1>Sworn</h1>
              <span className="tag">execution integrity for Uniswap v4</span>
            </div>
            <nav>
              {NAV.map(([href, label]) => (
                <a key={href} href={href}>
                  {label}
                </a>
              ))}
            </nav>
          </div>
        </header>
        <main className="wrap">{children}</main>
      </body>
    </html>
  );
}
