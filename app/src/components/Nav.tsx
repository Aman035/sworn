'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV = [
  ['/hooks', 'Hooks'],
  ['/detection', 'Detection'],
  ['/attribution', 'Attribution'],
] as const;

/**
 * The mark: a seal with an equals struck into it.
 *
 * "Sworn" is an oath and an oath is sealed; what this one attests is the router's single
 * assertion, `executedDelta == probed[chosen]`. Inline rather than an <img> so it takes
 * `currentColor` and stays crisp at every size the nav uses.
 *
 * Geometry is kept in step with `scripts/render_graphics.py`, which renders the same mark
 * for the favicon, the README banner and the social image.
 */
function Mark() {
  return (
    <svg className="mark-glyph" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <path
        d="M53 32 A21 21 0 1 1 42 13.6 L53 20 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="6.6"
        strokeLinejoin="round"
      />
      <g stroke="currentColor" strokeWidth="6.6" strokeLinecap="round">
        <path d="M21.5 27 H42.5" />
        <path d="M21.5 38 H42.5" />
      </g>
    </svg>
  );
}

export function Nav() {
  const pathname = usePathname();

  const links = NAV.map(([href, label]) => {
    const active = pathname === href || pathname === `${href}/`;
    return (
      <Link key={href} href={href} aria-current={active ? 'page' : undefined}>
        {label}
      </Link>
    );
  });

  return (
    <nav className="floatnav" aria-label="Sections">
      <Link href="/" className="floatnav-mark" aria-label="Sworn, home">
        <Mark />
        <span>SWORN</span>
      </Link>
      <div className="floatnav-links">{links}</div>
    </nav>
  );
}
