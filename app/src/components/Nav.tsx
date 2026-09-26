'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

/**
 * `[=]` — the assertion the router makes, `executedDelta == probed[chosen]`: equality,
 * enforced inside a boundary. Inline rather than an <img> so it inherits `currentColor`
 * and stays crisp at every size the nav uses.
 */
function Mark() {
  return (
    <svg className="mark-glyph" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <g fill="none" stroke="currentColor" strokeWidth="6.2" strokeLinecap="square">
        <path d="M19 15 H13 V49 H19" />
        <path d="M45 15 H51 V49 H45" />
        <path d="M25 27.5 H39" />
        <path d="M25 36.5 H39" />
      </g>
    </svg>
  );
}

const NAV = [
  ['/hooks', 'Hooks'],
  ['/detection', 'Detection'],
  ['/attribution', 'Attribution'],
] as const;

/**
 * Two states, one component.
 *
 * On the landing page the nav floats over the hero as a glass pill, because the hero is
 * the thing worth looking at and chrome above it would push it down. Everywhere else it
 * sits in a masthead with the wordmark, because those pages are read rather than watched.
 */
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
