'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV = [
  ['/overview', 'Overview'],
  ['/hooks', 'Hook explorer'],
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
  const onLanding = pathname === '/' || pathname === '';

  const links = NAV.map(([href, label]) => {
    const active = pathname === href || pathname === `${href}/`;
    return (
      <Link key={href} href={href} aria-current={active ? 'page' : undefined}>
        {label}
      </Link>
    );
  });

  if (onLanding) {
    return (
      <nav className="floatnav" aria-label="Sections">
        <Link href="/" className="floatnav-mark">
          SWORN
        </Link>
        <div className="floatnav-links">{links}</div>
      </nav>
    );
  }

  return (
    <header className="masthead">
      <div className="masthead-inner">
        <Link href="/" className="wordmark">
          SWORN
        </Link>
        <p className="standfirst">
          A hook is arbitrary code inside every swap. This is what they actually do.
        </p>
        <nav aria-label="Sections">{links}</nav>
      </div>
    </header>
  );
}
