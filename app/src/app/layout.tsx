import type { Metadata } from 'next';
import { Nav } from '@/components/Nav';
import './globals.css';

export const metadata: Metadata = {
  title: 'Sworn — execution integrity for Uniswap v4',
  description:
    'Measured hook divergence across Uniswap v4 on mainnet, and a router that makes quote spoofing structurally impossible.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* Runs before paint so the reveal animation can be opt-in: see `.reveal` in
            globals.css. Without this the page still renders, just without the motion. */}
        <script
          dangerouslySetInnerHTML={{ __html: "document.documentElement.classList.add('js')" }}
        />
      </head>
      <body>
        <Nav />

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
