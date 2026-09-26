import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';

export const metadata: Metadata = {
  title: 'Sworn — execution integrity for Uniswap v4',
  description:
    'Measured hook divergence across Uniswap v4 on mainnet, and a router that makes quote spoofing structurally impossible.',
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
        <header className="masthead">
          <div className="masthead-inner">
            <p className="wordmark">SWORN</p>
            <p className="standfirst">
              A hook is arbitrary code inside every swap. This is what they actually do.
            </p>
            <nav aria-label="Sections">
              {/* `Link`, not `<a>`: Next rewrites these for `basePath`, and a plain
                  anchor would send every nav click to the domain root on a project site
                  served from /<repo>/. */}
              {NAV.map(([href, label]) => (
                <Link key={href} href={href}>
                  {label}
                </Link>
              ))}
            </nav>
          </div>
        </header>

        <main>{children}</main>

        <footer className="colophon">
          <p>
            Every figure here was produced by a pipeline in this repository from a snapshot with a
            recorded sha256. Nothing is entered by hand, and nothing is estimated.
          </p>
          <p>
            Re-derive any of it: <code className="addr">make phase-2</code> for the census,{' '}
            <code className="addr">make phase-3</code> for settled trades,{' '}
            <code className="addr">make phase-4</code> for detection.
          </p>
        </footer>
      </body>
    </html>
  );
}
